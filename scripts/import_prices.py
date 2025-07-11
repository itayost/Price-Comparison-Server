# price_comparison_server/scripts/import_prices.py

import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Set, Optional
import logging
from datetime import datetime
from sqlalchemy import func
import re

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.connection import get_db
from database.new_models import Chain, Branch, ChainProduct, BranchPrice
from parsers import get_parser

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class PriceImporter:
    """Import price data from chains to database"""

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
        self.skipped_stores: Set[str] = set()
        self.processed_stores: Set[str] = set()

    def import_chain_prices(self, chain_name: str, limit_files: int = None):
        """Import prices for a specific chain"""
        logger.info(f"\n{'='*60}")
        logger.info(f"Starting price import for {chain_name}")
        logger.info(f"{'='*60}")

        # Get parser
        parser = get_parser(chain_name)
        if not parser:
            logger.error(f"No parser available for {chain_name}")
            return

        # Get branch mappings (store_id -> branch_id)
        branch_mappings = self.get_branch_mappings(chain_name)
        if not branch_mappings:
            logger.error(f"No branches found for {chain_name}.")
            logger.info("Did you import stores first?")
            logger.info("Run: python scripts/import_chain_data.py")
            return

        logger.info(f"Found {len(branch_mappings)} branches for {chain_name}")
        logger.debug(f"Branch mappings sample: {list(branch_mappings.items())[:5]}")

        # Get price file URLs
        logger.info("Fetching price file URLs...")
        try:
            price_urls = parser.get_price_file_urls()
        except Exception as e:
            logger.error(f"Failed to get price URLs: {e}")
            return

        if not price_urls:
            logger.warning(f"No price files found for {chain_name}")
            return

        logger.info(f"Found {len(price_urls)} price files")

        # Limit files if requested (for testing)
        if limit_files:
            price_urls = price_urls[:limit_files]
            logger.info(f"Limited to {len(price_urls)} files for testing")

        # Process each price file
        for i, url in enumerate(price_urls, 1):
            logger.info(f"\nProcessing file {i}/{len(price_urls)}: {url.split('/')[-1]}")

            # Try to extract store ID from URL
            store_id_from_url = self.extract_store_id_from_url(url, chain_name)
            if store_id_from_url:
                logger.debug(f"Extracted store ID from URL: {store_id_from_url}")

            self.process_price_file(chain_name, parser, url, branch_mappings, store_id_from_url)

            # Log progress every 5 files
            if i % 5 == 0:
                self.log_progress()

        # Final summary
        logger.info(f"\n{'='*50}")
        logger.info(f"Completed {chain_name} import")
        logger.info(f"Processed stores: {sorted(self.processed_stores)}")
        logger.info(f"Skipped stores: {sorted(self.skipped_stores)}")

    def extract_store_id_from_url(self, url: str, chain_name: str) -> Optional[str]:
        """Try to extract store ID from URL"""
        # Common patterns in price file URLs
        patterns = [
            r'Store(\d+)',  # Store123
            r'store[_-]?(\d+)',  # store_123 or store-123
            r'Price[^0-9]*(\d+)',  # Price123 or Price_Full_123
            r'(\d+)\.xml',  # 123.xml
        ]

        filename = url.split('/')[-1]
        for pattern in patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                store_id = match.group(1)
                # Remove leading zeros for consistency
                return str(int(store_id))

        return None

    def get_branch_mappings(self, chain_name: str) -> Dict[str, int]:
        """Get mapping of store_id to branch_id for a chain"""
        mappings = {}

        with get_db() as db:
            chain = db.query(Chain).filter(Chain.name == chain_name).first()
            if not chain:
                logger.error(f"Chain '{chain_name}' not found in database")
                return mappings

            branches = db.query(Branch).filter(Branch.chain_id == chain.chain_id).all()
            for branch in branches:
                mappings[branch.store_id] = branch.branch_id
                # Also try with leading zeros removed
                mappings[str(int(branch.store_id))] = branch.branch_id

        logger.info(f"Created mappings for {len(set(mappings.values()))} unique branches")
        return mappings

    def process_price_file(self, chain_name: str, parser, url: str,
                          branch_mappings: Dict[str, int], store_id_hint: Optional[str] = None):
        """Process a single price file"""
        try:
            # Download and parse file
            logger.debug(f"Downloading: {url}")
            content = parser.download_gz_file(url)

            if not content:
                logger.error(f"Failed to download {url}")
                self.stats['errors'] += 1
                return

            # Parse prices
            prices = parser.parse_price_data(content)

            if not prices:
                logger.warning(f"No prices parsed from {url}")
                self.stats['files_skipped'] += 1
                return

            logger.info(f"Parsed {len(prices)} prices")

            # Check if all prices have the same store_id
            store_ids = set(p.get('store_id') for p in prices if p.get('store_id'))

            if not store_ids and store_id_hint:
                # Use hint from URL if no store ID in data
                logger.info(f"Using store ID from URL: {store_id_hint}")
                for price in prices:
                    price['store_id'] = store_id_hint
                store_ids = {store_id_hint}

            if len(store_ids) == 0:
                logger.error(f"No store ID found in file or URL: {url}")
                self.stats['files_skipped'] += 1
                return
            elif len(store_ids) > 1:
                logger.warning(f"Multiple store IDs found in file: {store_ids}")

            # Log which store we're processing
            for store_id in store_ids:
                if store_id in branch_mappings:
                    self.processed_stores.add(store_id)
                    branch = self.get_branch_info(branch_mappings[store_id])
                    logger.info(f"Processing store {store_id}: {branch}")
                else:
                    self.skipped_stores.add(store_id)
                    logger.warning(f"Store {store_id} not found in branch mappings - skipping")

            # Import prices in batches
            self.import_price_batch(chain_name, prices, branch_mappings)
            self.stats['files_processed'] += 1

        except Exception as e:
            logger.error(f"Error processing price file {url}: {e}")
            self.stats['errors'] += 1
            import traceback
            traceback.print_exc()

    def get_branch_info(self, branch_id: int) -> str:
        """Get branch name and city for logging"""
        with get_db() as db:
            branch = db.query(Branch).filter(Branch.branch_id == branch_id).first()
            if branch:
                return f"{branch.name} ({branch.city})"
            return f"Branch {branch_id}"

    def import_price_batch(self, chain_name: str, prices: List[Dict], branch_mappings: Dict[str, int]):
        """Import a batch of prices"""
        with get_db() as db:
            chain = db.query(Chain).filter(Chain.name == chain_name).first()
            if not chain:
                logger.error(f"Chain '{chain_name}' not found")
                return

            # Process in smaller batches to avoid memory issues
            batch_size = 1000
            for i in range(0, len(prices), batch_size):
                batch = prices[i:i + batch_size]
                self._process_batch(db, chain.chain_id, batch, branch_mappings)

                # Commit after each batch
                try:
                    db.commit()
                    logger.debug(f"Committed batch {i//batch_size + 1}")
                except Exception as e:
                    logger.error(f"Failed to commit batch: {e}")
                    db.rollback()

    def _process_batch(self, db, chain_id: int, batch: List[Dict], branch_mappings: Dict[str, int]):
        """Process a single batch of prices"""
        for price_data in batch:
            try:
                # Skip if branch not found
                store_id = price_data.get('store_id')
                if not store_id:
                    continue

                # Try exact match first, then with leading zeros removed
                branch_id = None
                if store_id in branch_mappings:
                    branch_id = branch_mappings[store_id]
                elif str(int(store_id)) in branch_mappings:
                    branch_id = branch_mappings[str(int(store_id))]

                if not branch_id:
                    self.stats['branches_skipped'] += 1
                    if store_id not in self.skipped_stores:
                        self.skipped_stores.add(store_id)
                        logger.debug(f"Skipping unknown store: {store_id}")
                    continue

                # Get or create chain product
                barcode = price_data.get('barcode')
                if not barcode:
                    continue

                # First try to get existing product
                chain_product = db.query(ChainProduct).filter(
                    ChainProduct.chain_id == chain_id,
                    ChainProduct.barcode == barcode
                ).first()

                if not chain_product:
                    # Create new chain product
                    chain_product = ChainProduct(
                        chain_id=chain_id,
                        barcode=barcode,
                        name=price_data.get('name', f'Product {barcode}')
                    )
                    db.add(chain_product)
                    db.flush()  # Get the ID without committing
                    self.stats['products_created'] += 1
                else:
                    # Update name if we have a better one
                    new_name = price_data.get('name')
                    if new_name and (not chain_product.name or len(new_name) > len(chain_product.name)):
                        chain_product.name = new_name
                        self.stats['products_updated'] += 1

                # Get or create price
                branch_price = db.query(BranchPrice).filter(
                    BranchPrice.chain_product_id == chain_product.chain_product_id,
                    BranchPrice.branch_id == branch_id
                ).first()

                price_value = float(price_data.get('price', 0))

                if branch_price:
                    # Update existing price only if changed
                    if float(branch_price.price) != price_value:
                        branch_price.price = price_value
                        branch_price.last_updated = datetime.utcnow()
                        self.stats['prices_updated'] += 1
                else:
                    # Create new price
                    branch_price = BranchPrice(
                        chain_product_id=chain_product.chain_product_id,
                        branch_id=branch_id,
                        price=price_value,
                        last_updated=datetime.utcnow()
                    )
                    db.add(branch_price)
                    self.stats['prices_created'] += 1

            except Exception as e:
                logger.error(f"Error processing item: {e}")
                self.stats['errors'] += 1

    def log_progress(self):
        """Log current import progress"""
        logger.info(f"\nProgress Update:")
        logger.info(f"  Files processed: {self.stats['files_processed']:,}")
        logger.info(f"  Products created: {self.stats['products_created']:,}")
        logger.info(f"  Products updated: {self.stats['products_updated']:,}")
        logger.info(f"  Prices created: {self.stats['prices_created']:,}")
        logger.info(f"  Prices updated: {self.stats['prices_updated']:,}")
        logger.info(f"  Branches skipped: {self.stats['branches_skipped']:,}")
        logger.info(f"  Stores processed: {len(self.processed_stores)}")
        logger.info(f"  Errors: {self.stats['errors']:,}")

    def show_summary(self):
        """Show final import summary"""
        logger.info(f"\n{'='*60}")
        logger.info("IMPORT SUMMARY")
        logger.info(f"{'='*60}")

        logger.info(f"Files processed: {self.stats['files_processed']:,}")
        logger.info(f"Files skipped: {self.stats['files_skipped']:,}")
        logger.info(f"Products created: {self.stats['products_created']:,}")
        logger.info(f"Products updated: {self.stats['products_updated']:,}")
        logger.info(f"Prices created: {self.stats['prices_created']:,}")
        logger.info(f"Prices updated: {self.stats['prices_updated']:,}")
        logger.info(f"Branches skipped: {self.stats['branches_skipped']:,}")
        logger.info(f"Errors: {self.stats['errors']:,}")

        logger.info(f"\nStores processed successfully: {len(self.processed_stores)}")
        logger.info(f"Stores skipped (not found): {len(self.skipped_stores)}")

        # Show database statistics
        with get_db() as db:
            logger.info(f"\nDatabase Statistics:")

            chains = db.query(Chain).all()
            for chain in chains:
                product_count = db.query(func.count(ChainProduct.chain_product_id))\
                    .filter(ChainProduct.chain_id == chain.chain_id).scalar()

                price_count = db.query(func.count(BranchPrice.price_id))\
                    .join(ChainProduct)\
                    .filter(ChainProduct.chain_id == chain.chain_id).scalar()

                branch_count = db.query(func.count(Branch.branch_id))\
                    .filter(Branch.chain_id == chain.chain_id).scalar()

                branches_with_prices = db.query(func.count(func.distinct(BranchPrice.branch_id)))\
                    .join(Branch)\
                    .filter(Branch.chain_id == chain.chain_id).scalar()

                logger.info(f"\n  {chain.display_name} ({chain.name}):")
                logger.info(f"    - Total branches: {branch_count:,}")
                logger.info(f"    - Branches with prices: {branches_with_prices:,} ({branches_with_prices/branch_count*100:.1f}%)")
                logger.info(f"    - Products: {product_count:,}")
                logger.info(f"    - Total prices: {price_count:,}")

                # Show coverage
                if branches_with_prices > 0:
                    avg_products_per_branch = price_count / branches_with_prices
                    logger.info(f"    - Avg products/branch with data: {avg_products_per_branch:,.0f}")


def main():
    """Main function"""
    import argparse

    parser = argparse.ArgumentParser(description='Import price data to Oracle database')
    parser.add_argument('--chain', choices=['shufersal', 'victory', 'all'],
                       default='all', help='Chain to import')
    parser.add_argument('--limit', type=int, help='Limit number of files to process (for testing)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    importer = PriceImporter()

    try:
        if args.chain == 'all':
            # Import both chains
            for chain in ['shufersal', 'victory']:
                importer.import_chain_prices(chain, args.limit)
                logger.info(f"\nCompleted {chain}")
        else:
            importer.import_chain_prices(args.chain, args.limit)

        # Show final summary
        importer.show_summary()

    except KeyboardInterrupt:
        logger.info("\n\nImport interrupted by user")
        importer.show_summary()
    except Exception as e:
        logger.error(f"Import failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
