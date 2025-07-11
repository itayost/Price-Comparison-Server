# price_comparison_server/scripts/import_prices.py
# Ultra-simple version for Oracle timeout issues

import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Set
import logging
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session
import re
import time

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.connection import get_db, SessionLocal, USE_ORACLE
from database.new_models import Chain, Branch, ChainProduct, BranchPrice
from parsers import get_parser

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class PriceImporter:
    """Ultra-simple price importer for Oracle"""

    def __init__(self):
        self.stats = {
            'products_created': 0,
            'products_updated': 0,
            'prices_created': 0,
            'prices_updated': 0,
            'errors': 0,
            'branches_skipped': 0,
            'files_processed': 0,
            'files_skipped': 0
        }
        # Ultra small batch for Oracle
        self.batch_size = 10 if USE_ORACLE else 50

    def import_chain_prices(self, chain_name: str, limit_files: int = None):
        """Import prices for a chain"""
        start_time = time.time()
        logger.info(f"\n{'='*60}")
        logger.info(f"Starting import for {chain_name}")
        logger.info(f"Batch size: {self.batch_size}")
        logger.info(f"{'='*60}")

        # Get parser
        parser = get_parser(chain_name)
        if not parser:
            logger.error(f"No parser for {chain_name}")
            return

        # Get branch mappings once
        branch_mappings = self._get_branch_mappings(chain_name)
        if not branch_mappings:
            logger.error(f"No branches found for {chain_name}")
            return

        logger.info(f"Found {len(branch_mappings)} branches")

        # Get price files
        price_urls = parser.get_price_file_urls()
        if not price_urls:
            logger.error(f"No price files found")
            return

        logger.info(f"Found {len(price_urls)} price files")

        if limit_files:
            price_urls = price_urls[:limit_files]
            logger.info(f"Limited to {limit_files} files")

        # Process each file
        for i, url in enumerate(price_urls, 1):
            filename = os.path.basename(url).split('?')[0]
            logger.info(f"\nFile {i}/{len(price_urls)}: {filename}")

            try:
                self._process_file(chain_name, parser, url, branch_mappings)
                self.stats['files_processed'] += 1
            except Exception as e:
                logger.error(f"Failed to process file: {e}")
                self.stats['files_skipped'] += 1

        # Summary
        elapsed = time.time() - start_time
        logger.info(f"\nCompleted in {elapsed:.1f} seconds")
        self._show_summary()

    def _get_branch_mappings(self, chain_name: str) -> Dict[str, int]:
        """Get store_id -> branch_id mappings"""
        mappings = {}

        with get_db() as db:
            chain = db.query(Chain).filter(Chain.name == chain_name).first()
            if not chain:
                return mappings

            branches = db.query(Branch).filter(Branch.chain_id == chain.chain_id).all()
            for branch in branches:
                mappings[branch.store_id] = branch.branch_id
                # Also without leading zeros
                try:
                    mappings[str(int(branch.store_id))] = branch.branch_id
                except:
                    pass

        return mappings

    def _process_file(self, chain_name: str, parser, url: str, branch_mappings: Dict[str, int]):
        """Process a single price file"""
        # Download
        content = parser.download_file(url)
        if not content:
            return

        # Parse
        prices = parser.parse_price_data(content)
        if not prices:
            return

        logger.info(f"Parsed {len(prices)} prices")

        # Extract store ID
        store_id = self._extract_store_id(prices, url)
        if not store_id:
            logger.error("No store ID found")
            return

        # Check if we have this branch
        branch_id = branch_mappings.get(store_id) or branch_mappings.get(str(int(store_id)))
        if not branch_id:
            logger.warning(f"Store {store_id} not in mappings")
            return

        # Log store info
        with get_db() as db:
            branch = db.query(Branch).filter(Branch.branch_id == branch_id).first()
            if branch:
                logger.info(f"Store {store_id}: {branch.name} ({branch.city})")

        # Filter valid prices
        valid_prices = []
        for price in prices:
            if price.get('barcode') and price.get('price'):
                price['branch_id'] = branch_id
                valid_prices.append(price)

        if not valid_prices:
            return

        logger.info(f"Processing {len(valid_prices)} prices")

        # Process in ultra-small batches
        self._import_prices_simple(chain_name, valid_prices)

    def _extract_store_id(self, prices: List[Dict], url: str) -> str:
        """Extract store ID from prices or URL"""
        # From prices
        store_ids = {p.get('store_id') for p in prices if p.get('store_id')}
        if store_ids:
            return str(int(list(store_ids)[0]))  # Remove leading zeros

        # From URL
        patterns = [r'-(\d{3})-', r'Store(\d+)', r'store[_-]?(\d+)']
        filename = url.split('/')[-1].split('?')[0]

        for pattern in patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                return str(int(match.group(1)))

        return None

    def _import_prices_simple(self, chain_name: str, prices: List[Dict]):
        """Import prices with ultra-simple logic"""
        total_batches = (len(prices) + self.batch_size - 1) // self.batch_size

        for i in range(0, len(prices), self.batch_size):
            batch = prices[i:i + self.batch_size]
            batch_num = (i // self.batch_size) + 1

            # Create new session for each batch
            session = SessionLocal()
            try:
                # Get chain
                chain = session.query(Chain).filter(Chain.name == chain_name).first()
                if not chain:
                    continue

                # Process batch
                self._process_ultra_simple_batch(session, chain.chain_id, batch)

                # Commit immediately
                session.commit()

                if batch_num % 10 == 0 or batch_num == total_batches:
                    logger.info(f"Progress: {batch_num}/{total_batches} batches")

            except Exception as e:
                session.rollback()
                logger.error(f"Batch {batch_num} failed: {str(e)[:100]}")
                self.stats['errors'] += len(batch)
            finally:
                session.close()

            # Small delay for Oracle
            if USE_ORACLE:
                time.sleep(0.1)

    def _process_ultra_simple_batch(self, session: Session, chain_id: int, batch: List[Dict]):
        """Process with minimal queries"""

        for item in batch:
            try:
                barcode = item['barcode']
                branch_id = item['branch_id']
                new_price = float(item.get('price', 0))
                name = item.get('name', '')[:255]

                # Get or create product (single query)
                product = session.query(ChainProduct).filter(
                    ChainProduct.chain_id == chain_id,
                    ChainProduct.barcode == barcode
                ).first()

                if not product:
                    product = ChainProduct(
                        chain_id=chain_id,
                        barcode=barcode,
                        name=name
                    )
                    session.add(product)
                    session.flush()
                    self.stats['products_created'] += 1

                # Get or create price (single query)
                price = session.query(BranchPrice).filter(
                    BranchPrice.chain_product_id == product.chain_product_id,
                    BranchPrice.branch_id == branch_id
                ).first()

                if price:
                    if price.price != new_price:
                        price.price = new_price
                        price.last_updated = datetime.utcnow()
                        self.stats['prices_updated'] += 1
                else:
                    price = BranchPrice(
                        chain_product_id=product.chain_product_id,
                        branch_id=branch_id,
                        price=new_price,
                        last_updated=datetime.utcnow()
                    )
                    session.add(price)
                    self.stats['prices_created'] += 1

            except Exception as e:
                logger.debug(f"Error processing item: {e}")
                self.stats['errors'] += 1

    def _show_summary(self):
        """Show import summary"""
        logger.info(f"\n{'='*60}")
        logger.info("IMPORT SUMMARY")
        logger.info(f"{'='*60}")

        for key, value in self.stats.items():
            logger.info(f"{key.replace('_', ' ').title()}: {value:,}")


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--chain', choices=['shufersal', 'victory'], default='shufersal')
    parser.add_argument('--limit', type=int, help='Limit files')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    importer = PriceImporter()

    try:
        importer.import_chain_prices(args.chain, args.limit)
    except KeyboardInterrupt:
        logger.info("\nInterrupted")
    except Exception as e:
        logger.error(f"Failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
