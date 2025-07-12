# scripts/import_prices_oracle.py
"""Oracle-optimized price importer with aggressive timeout handling"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Set, Optional
import logging
from datetime import datetime
from sqlalchemy import text, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.exc import DatabaseError, DisconnectionError, OperationalError
import re
import time
import oracledb

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.new_models import Chain, Branch, ChainProduct, BranchPrice
from parsers import get_parser

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Oracle-specific configuration
oracledb.defaults.config_dir = os.getenv("TNS_ADMIN", "./wallet")
oracledb.defaults.tcp_connect_timeout = 30.0
oracledb.defaults.call_timeout = 60000  # 60 seconds in milliseconds


class OracleOptimizedImporter:
    """Price importer optimized for Oracle Cloud with timeout handling"""

    def __init__(self):
        self.stats = {
            'products_created': 0,
            'products_updated': 0,
            'prices_created': 0,
            'prices_updated': 0,
            'errors': 0,
            'branches_skipped': 0,
            'files_processed': 0,
            'files_skipped': 0,
            'connection_retries': 0
        }

        # Oracle-optimized batch sizes
        self.batch_size = 5 if self._is_oracle() else 50
        self.commit_interval = 10  # Commit every N batches

        # Connection pool settings
        self.engine = self._create_engine()
        self.SessionLocal = sessionmaker(bind=self.engine)

    def _is_oracle(self) -> bool:
        """Check if using Oracle database"""
        return os.getenv("USE_ORACLE", "false").lower() == "true"

    def _create_engine(self):
        """Create SQLAlchemy engine with Oracle optimizations"""
        if self._is_oracle():
            # Oracle configuration
            user = os.getenv("ORACLE_USER")
            password = os.getenv("ORACLE_PASSWORD")
            dsn = os.getenv("ORACLE_DSN", "champdb_low")

            # Create connection string
            connection_string = f"oracle+oracledb://{user}:{password}@{dsn}"

            # Create engine with NullPool to avoid connection pooling issues
            engine = create_engine(
                connection_string,
                poolclass=NullPool,
                connect_args={
                    "config_dir": os.getenv("TNS_ADMIN", "./wallet"),
                    "tcp_connect_timeout": 30,
                    "retry_count": 3,
                    "retry_delay": 1
                }
            )
        else:
            # SQLite configuration
            database_url = os.getenv("DATABASE_URL", "sqlite:///./price_comparison.db")
            engine = create_engine(database_url)

        return engine

    def _get_session_with_retry(self, max_retries: int = 3) -> Session:
        """Get database session with retry logic"""
        for attempt in range(max_retries):
            try:
                session = self.SessionLocal()
                # Test connection
                session.execute(text("SELECT 1"))
                return session
            except (DatabaseError, DisconnectionError, OperationalError) as e:
                self.stats['connection_retries'] += 1
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"Connection failed (attempt {attempt + 1}), retrying in {wait_time}s: {str(e)[:100]}")
                    time.sleep(wait_time)
                else:
                    raise

    def import_chain_prices(self, chain_name: str, limit_files: Optional[int] = None):
        """Import prices for a chain with Oracle optimizations"""
        start_time = time.time()
        logger.info(f"\n{'='*60}")
        logger.info(f"Starting Oracle-optimized import for {chain_name}")
        logger.info(f"Batch size: {self.batch_size}, Commit interval: {self.commit_interval}")
        logger.info(f"{'='*60}")

        # Get parser
        parser = get_parser(chain_name)
        if not parser:
            logger.error(f"No parser for {chain_name}")
            return

        # Get branch mappings
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
                self._process_file_with_retry(chain_name, parser, url, branch_mappings)
                self.stats['files_processed'] += 1
            except Exception as e:
                logger.error(f"Failed to process file after retries: {str(e)[:200]}")
                self.stats['files_skipped'] += 1

        # Summary
        elapsed = time.time() - start_time
        logger.info(f"\nCompleted in {elapsed:.1f} seconds")
        self._show_summary()

    def _get_branch_mappings(self, chain_name: str) -> Dict[str, int]:
        """Get store_id -> branch_id mappings with retry"""
        mappings = {}

        session = self._get_session_with_retry()
        try:
            chain = session.query(Chain).filter(Chain.name == chain_name).first()
            if not chain:
                return mappings

            branches = session.query(Branch).filter(Branch.chain_id == chain.chain_id).all()
            for branch in branches:
                mappings[branch.store_id] = branch.branch_id
                # Also without leading zeros
                try:
                    mappings[str(int(branch.store_id))] = branch.branch_id
                except:
                    pass

            return mappings
        finally:
            session.close()

    def _process_file_with_retry(self, chain_name: str, parser, url: str,
                                  branch_mappings: Dict[str, int], max_retries: int = 3):
        """Process a file with retry logic"""
        for attempt in range(max_retries):
            try:
                # Download file
                content = parser.download_file(url)
                if not content:
                    logger.warning(f"No content downloaded from {url}")
                    return

                # Parse prices
                prices = parser.parse_price_data(content)
                if not prices:
                    logger.warning(f"No prices parsed from {url}")
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
                    self.stats['branches_skipped'] += 1
                    return

                # Process prices in micro-batches
                self._import_prices_oracle_optimized(chain_name, branch_id, prices)
                return

            except (DatabaseError, DisconnectionError, OperationalError) as e:
                if attempt < max_retries - 1:
                    wait_time = 5 * (attempt + 1)
                    logger.warning(f"Database error processing file (attempt {attempt + 1}), retrying in {wait_time}s")
                    time.sleep(wait_time)
                else:
                    raise
            except Exception as e:
                logger.error(f"Unexpected error processing file: {str(e)[:200]}")
                raise

    def _extract_store_id(self, prices: List[Dict], url: str) -> Optional[str]:
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

    def _import_prices_oracle_optimized(self, chain_name: str, branch_id: int, prices: List[Dict]):
        """Import prices with Oracle-specific optimizations"""
        total_batches = (len(prices) + self.batch_size - 1) // self.batch_size

        # Create session for entire import
        session = self._get_session_with_retry()
        try:
            # Get chain once
            chain = session.query(Chain).filter(Chain.name == chain_name).first()
            if not chain:
                logger.error(f"Chain {chain_name} not found")
                return

            # Pre-fetch existing products and prices for this branch
            existing_products = self._get_existing_products(session, chain.chain_id, prices)
            existing_prices = self._get_existing_prices(session, branch_id)

            # Process in micro-batches
            batch_count = 0
            for i in range(0, len(prices), self.batch_size):
                batch = prices[i:i + self.batch_size]
                batch_num = (i // self.batch_size) + 1

                try:
                    self._process_batch_optimized(
                        session, chain.chain_id, branch_id,
                        batch, existing_products, existing_prices
                    )

                    batch_count += 1

                    # Commit at intervals
                    if batch_count % self.commit_interval == 0 or batch_num == total_batches:
                        session.commit()
                        logger.info(f"Committed batch {batch_num}/{total_batches}")

                        # Small delay for Oracle
                        if self._is_oracle():
                            time.sleep(0.1)

                except Exception as e:
                    session.rollback()
                    logger.error(f"Batch {batch_num} failed: {str(e)[:100]}")
                    self.stats['errors'] += len(batch)
                    # Continue with next batch

            # Final commit
            session.commit()

        finally:
            session.close()

    def _get_existing_products(self, session: Session, chain_id: int,
                               prices: List[Dict]) -> Dict[str, ChainProduct]:
        """Pre-fetch existing products to minimize queries"""
        barcodes = {p['barcode'] for p in prices if p.get('barcode')}

        existing = session.query(ChainProduct).filter(
            ChainProduct.chain_id == chain_id,
            ChainProduct.barcode.in_(list(barcodes))
        ).all()

        return {p.barcode: p for p in existing}

    def _get_existing_prices(self, session: Session, branch_id: int) -> Set[int]:
        """Pre-fetch existing price product IDs for branch"""
        prices = session.query(BranchPrice.chain_product_id).filter(
            BranchPrice.branch_id == branch_id
        ).all()

        return {p[0] for p in prices}

    def _process_batch_optimized(self, session: Session, chain_id: int, branch_id: int,
                                 batch: List[Dict], existing_products: Dict[str, ChainProduct],
                                 existing_price_product_ids: Set[int]):
        """Process batch with minimal queries"""

        for item in batch:
            try:
                barcode = item['barcode']
                new_price = float(item.get('price', 0))
                name = item.get('name', '')[:255]

                # Get or create product
                if barcode in existing_products:
                    product = existing_products[barcode]
                else:
                    # Create new product
                    product = ChainProduct(
                        chain_id=chain_id,
                        barcode=barcode,
                        name=name
                    )
                    session.add(product)
                    session.flush()  # Get ID
                    existing_products[barcode] = product
                    self.stats['products_created'] += 1

                # Check if price exists
                if product.chain_product_id in existing_price_product_ids:
                    # Update existing price
                    session.execute(
                        text("""
                            UPDATE branch_prices
                            SET price = :price, last_updated = :updated
                            WHERE chain_product_id = :product_id
                            AND branch_id = :branch_id
                        """),
                        {
                            'price': new_price,
                            'updated': datetime.utcnow(),
                            'product_id': product.chain_product_id,
                            'branch_id': branch_id
                        }
                    )
                    self.stats['prices_updated'] += 1
                else:
                    # Create new price
                    price = BranchPrice(
                        chain_product_id=product.chain_product_id,
                        branch_id=branch_id,
                        price=new_price,
                        last_updated=datetime.utcnow()
                    )
                    session.add(price)
                    existing_price_product_ids.add(product.chain_product_id)
                    self.stats['prices_created'] += 1

            except Exception as e:
                logger.debug(f"Error processing item {item.get('barcode', 'unknown')}: {str(e)[:100]}")
                self.stats['errors'] += 1

    def _show_summary(self):
        """Show import summary"""
        logger.info(f"\n{'='*60}")
        logger.info("Import Summary:")
        logger.info(f"{'='*60}")
        logger.info(f"Files processed: {self.stats['files_processed']}")
        logger.info(f"Files skipped: {self.stats['files_skipped']}")
        logger.info(f"Products created: {self.stats['products_created']}")
        logger.info(f"Products updated: {self.stats['products_updated']}")
        logger.info(f"Prices created: {self.stats['prices_created']}")
        logger.info(f"Prices updated: {self.stats['prices_updated']}")
        logger.info(f"Branches skipped: {self.stats['branches_skipped']}")
        logger.info(f"Connection retries: {self.stats['connection_retries']}")
        logger.info(f"Errors: {self.stats['errors']}")
        logger.info(f"{'='*60}")


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Import prices with Oracle optimizations')
    parser.add_argument('--chain', choices=['shufersal', 'victory'],
                        help='Import specific chain only')
    parser.add_argument('--limit', type=int, default=0,
                        help='Limit number of files to process (0 = no limit)')
    parser.add_argument('--batch-size', type=int,
                        help='Override batch size')

    args = parser.parse_args()

    importer = OracleOptimizedImporter()

    if args.batch_size:
        importer.batch_size = args.batch_size
        logger.info(f"Using custom batch size: {args.batch_size}")

    chains = [args.chain] if args.chain else ['shufersal', 'victory']

    for chain in chains:
        importer.import_chain_prices(chain, args.limit if args.limit > 0 else None)


if __name__ == "__main__":
    main()
