# scripts/import_prices_optimized.py

import os
import sys
import time
import logging
from pathlib import Path
from typing import Dict, List, Any, Set
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
import threading
import queue

import pandas as pd
from sqlalchemy import text, bindparam
from sqlalchemy.orm import Session

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.connection import get_db_with_retry, USE_ORACLE, engine
from database.new_models import Chain, Branch, ChainProduct, BranchPrice
from parsers import get_parser

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class OptimizedPriceImporter:
    """Optimized price importer for Oracle Cloud"""

    def __init__(self):
        self.stats = defaultdict(int)
        self.stats_lock = threading.Lock()

        # Optimal batch sizes based on testing
        self.batch_size = 25000 if USE_ORACLE else 1000
        self.commit_size = 100000 if USE_ORACLE else 10000

        # Thread pool for parallel processing
        self.max_workers = 4 if USE_ORACLE else 2

        # Queue for batching
        self.batch_queue = queue.Queue(maxsize=100)

        logger.info(f"Initialized with batch_size={self.batch_size}, workers={self.max_workers}")

    def import_chain_prices(self, chain_name: str, limit_files: int = None):
        """Import prices for a chain with parallel processing"""
        start_time = time.time()

        logger.info(f"\n{'='*60}")
        logger.info(f"Starting optimized import for {chain_name}")
        logger.info(f"Batch size: {self.batch_size}, Workers: {self.max_workers}")
        logger.info(f"{'='*60}")

        # Get parser
        parser = get_parser(chain_name)
        if not parser:
            logger.error(f"No parser for {chain_name}")
            return

        # Pre-load data for efficient lookups
        logger.info("Loading branch and product mappings...")
        branch_map, chain_id = self._load_branch_mappings(chain_name)
        product_cache = {}  # Will be populated on demand

        if not branch_map:
            logger.error(f"No branches found for {chain_name}")
            return

        logger.info(f"Found {len(branch_map)} branches")

        # Get price files
        price_urls = parser.get_price_file_urls()
        if limit_files:
            price_urls = price_urls[:limit_files]

        logger.info(f"Processing {len(price_urls)} price files")

        # Start worker threads
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Start batch processor
            batch_processor = executor.submit(self._batch_processor, chain_id, product_cache)

            # Submit file processing tasks
            futures = []
            for i, url in enumerate(price_urls):
                future = executor.submit(
                    self._process_file_parallel,
                    parser, url, branch_map, i, len(price_urls)
                )
                futures.append(future)

            # Wait for all files to be processed
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"File processing failed: {e}")

            # Signal batch processor to stop
            self.batch_queue.put(None)
            batch_processor.result()

        # Final summary
        elapsed = time.time() - start_time
        self._show_summary(elapsed)

    def _load_branch_mappings(self, chain_name: str) -> tuple:
        """Load branch mappings with efficient query"""
        mappings = {}
        chain_id = None

        with get_db_with_retry() as db:
            # Get chain
            chain = db.query(Chain).filter(Chain.name == chain_name).first()
            if not chain:
                return mappings, None

            chain_id = chain.chain_id

            # Load all branches at once with city information for logging
            branches = db.query(
                Branch.branch_id,
                Branch.store_id,
                Branch.city  # Include city for verification
            ).filter(
                Branch.chain_id == chain_id
            ).all()

            # Count cities (all should be standardized already)
            city_counts = {}

            for branch_id, store_id, city in branches:
                mappings[store_id] = branch_id
                # Also map without leading zeros
                try:
                    mappings[str(int(store_id))] = branch_id
                except:
                    pass

                # Count cities
                city_counts[city] = city_counts.get(city, 0) + 1

            # Log city distribution
            logger.info(f"Loaded {len(branches)} branches across {len(city_counts)} cities")
            logger.info(f"Top cities: {sorted(city_counts.items(), key=lambda x: x[1], reverse=True)[:5]}")

        return mappings, chain_id

    def _process_file_parallel(self, parser, url: str, branch_map: dict,
                               file_num: int, total_files: int):
        """Process a single file and queue batches"""
        filename = os.path.basename(url).split('?')[0]
        logger.info(f"Processing file {file_num + 1}/{total_files}: {filename}")

        try:
            # Download and parse
            content = parser.download_file(url)
            if not content:
                return

            prices = parser.parse_price_data(content)
            if not prices:
                return

            # Group by store
            store_prices = defaultdict(list)
            for price in prices:
                store_id = price.get('store_id')
                if store_id:
                    store_prices[store_id].append(price)

            # Process each store's prices
            for store_id, items in store_prices.items():
                # Find branch
                branch_id = branch_map.get(store_id) or branch_map.get(str(int(store_id)))
                if not branch_id:
                    continue

                # Queue for batch processing
                batch_data = {
                    'branch_id': branch_id,
                    'items': items
                }

                self.batch_queue.put(batch_data)

                with self.stats_lock:
                    self.stats['files_processed'] += 1

        except Exception as e:
            logger.error(f"Error processing file {filename}: {e}")
            with self.stats_lock:
                self.stats['files_failed'] += 1

    def _batch_processor(self, chain_id: int, product_cache: dict):
        """Process batches from queue"""
        batch_buffer = []

        while True:
            try:
                # Get batch data with timeout
                batch_data = self.batch_queue.get(timeout=5)

                if batch_data is None:  # Stop signal
                    break

                batch_buffer.append(batch_data)

                # Process when buffer is full
                if len(batch_buffer) >= 10:
                    self._process_batch_buffer(batch_buffer, chain_id, product_cache)
                    batch_buffer = []

            except queue.Empty:
                # Process remaining items
                if batch_buffer:
                    self._process_batch_buffer(batch_buffer, chain_id, product_cache)
                    batch_buffer = []
            except Exception as e:
                logger.error(f"Batch processor error: {e}")

        # Final processing
        if batch_buffer:
            self._process_batch_buffer(batch_buffer, chain_id, product_cache)

    def _process_batch_buffer(self, batch_buffer: list, chain_id: int,
                              product_cache: dict):
        """Process accumulated batches efficiently"""
        if not batch_buffer:
            return

        with get_db_with_retry() as session:
            try:
                # Prepare bulk data
                all_products = []
                all_prices = []

                for batch_data in batch_buffer:
                    branch_id = batch_data['branch_id']

                    for item in batch_data['items']:
                        barcode = item.get('barcode')
                        if not barcode:
                            continue

                        # Get or create product
                        if barcode not in product_cache:
                            product = self._get_or_create_product(
                                session, chain_id, barcode, item.get('name', '')
                            )
                            product_cache[barcode] = product.chain_product_id

                        # Prepare price data
                        price_data = {
                            'chain_product_id': product_cache[barcode],
                            'branch_id': branch_id,
                            'price': float(item.get('price', 0)),
                            'last_updated': datetime.utcnow()
                        }
                        all_prices.append(price_data)

                # Bulk upsert prices
                if all_prices:
                    self._bulk_upsert_prices(session, all_prices)

                session.commit()

                with self.stats_lock:
                    self.stats['prices_processed'] += len(all_prices)

            except Exception as e:
                session.rollback()
                logger.error(f"Batch processing error: {e}")
                with self.stats_lock:
                    self.stats['errors'] += len(batch_buffer)

    def _get_or_create_product(self, session: Session, chain_id: int,
                                barcode: str, name: str) -> ChainProduct:
        """Get or create product efficiently"""
        # Try to get existing
        product = session.query(ChainProduct).filter(
            ChainProduct.chain_id == chain_id,
            ChainProduct.barcode == barcode
        ).first()

        if not product:
            product = ChainProduct(
                chain_id=chain_id,
                barcode=barcode,
                name=name[:255]  # Ensure fits in column
            )
            session.add(product)
            session.flush()  # Get ID without committing

            with self.stats_lock:
                self.stats['products_created'] += 1

        return product

    def _bulk_upsert_prices(self, session: Session, price_data: list):
        """Bulk upsert prices using Oracle MERGE or PostgreSQL ON CONFLICT"""
        if USE_ORACLE:
            # Use MERGE for Oracle
            merge_sql = text("""
                MERGE INTO branch_prices bp
                USING (
                    SELECT :chain_product_id as chain_product_id,
                           :branch_id as branch_id,
                           :price as price,
                           :last_updated as last_updated
                    FROM dual
                ) src
                ON (bp.chain_product_id = src.chain_product_id
                    AND bp.branch_id = src.branch_id)
                WHEN MATCHED THEN
                    UPDATE SET bp.price = src.price,
                               bp.last_updated = src.last_updated
                WHEN NOT MATCHED THEN
                    INSERT (price_id, chain_product_id, branch_id, price, last_updated)
                    VALUES (price_id_seq.NEXTVAL, src.chain_product_id,
                            src.branch_id, src.price, src.last_updated)
            """)

            # Execute in batches
            for i in range(0, len(price_data), self.batch_size):
                batch = price_data[i:i + self.batch_size]
                session.execute(merge_sql, batch)

                with self.stats_lock:
                    self.stats['prices_updated'] += len(batch)
        else:
            # For SQLite/PostgreSQL, use simpler approach
            for price in price_data:
                existing = session.query(BranchPrice).filter(
                    BranchPrice.chain_product_id == price['chain_product_id'],
                    BranchPrice.branch_id == price['branch_id']
                ).first()

                if existing:
                    existing.price = price['price']
                    existing.last_updated = price['last_updated']
                else:
                    session.add(BranchPrice(**price))

    def _show_summary(self, elapsed_time: float):
        """Show import summary"""
        logger.info(f"\n{'='*60}")
        logger.info("IMPORT SUMMARY")
        logger.info(f"{'='*60}")

        with self.stats_lock:
            for key, value in sorted(self.stats.items()):
                logger.info(f"{key.replace('_', ' ').title()}: {value:,}")

        logger.info(f"\nTotal time: {elapsed_time:.1f} seconds")

        if self.stats['prices_processed'] > 0:
            rate = self.stats['prices_processed'] / elapsed_time
            logger.info(f"Processing rate: {rate:,.0f} prices/second")

def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--chain', choices=['shufersal', 'victory'], required=True)
    parser.add_argument('--limit', type=int, help='Limit files to process')
    parser.add_argument('--workers', type=int, help='Number of worker threads')
    args = parser.parse_args()

    importer = OptimizedPriceImporter()

    if args.workers:
        importer.max_workers = args.workers

    try:
        importer.import_chain_prices(args.chain, args.limit)
    except KeyboardInterrupt:
        logger.info("\nImport interrupted")
    except Exception as e:
        logger.error(f"Import failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
