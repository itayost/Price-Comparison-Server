# Enhanced scripts/import_chain_data.py with Oracle timeout handling

import os
import sys
from pathlib import Path
from typing import Dict, List, Any
import logging
import argparse
import time
from sqlalchemy.exc import DatabaseError, DisconnectionError

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.connection import get_db_with_retry  # Use the retry version
from database.new_models import Chain, Branch, Product, ChainProduct, BranchPrice
from parsers import get_parser, get_all_parsers, PARSER_REGISTRY
from sqlalchemy import func
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ChainDataImporter:
    """Main class for importing chain data with Oracle resilience"""

    def __init__(self):
        self.branch_mappings = {}  # Maps store_id to branch_id for each chain

    def import_stores(self, chain_name: str, stores: List[Dict[str, Any]]) -> int:
        """Import stores to database with retry logic"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with get_db_with_retry() as db:
                    # Get chain
                    chain = db.query(Chain).filter(Chain.name == chain_name).first()
                    if not chain:
                        logger.error(f"Chain '{chain_name}' not found in database")
                        logger.info(f"Creating chain '{chain_name}'")
                        chain = Chain(name=chain_name, display_name=chain_name.title())
                        db.add(chain)
                        db.flush()

                    imported = 0
                    updated = 0

                    # Create mapping for this chain
                    self.branch_mappings[chain_name] = {}

                    # Process stores in smaller batches to avoid timeouts
                    batch_size = 50  # Smaller batches for Oracle
                    for i in range(0, len(stores), batch_size):
                        batch = stores[i:i + batch_size]

                        for store_data in batch:
                            try:
                                # Check if branch exists
                                existing = db.query(Branch).filter(
                                    Branch.chain_id == chain.chain_id,
                                    Branch.store_id == store_data['store_id']
                                ).first()

                                if existing:
                                    # Update existing branch
                                    existing.name = store_data['store_name']
                                    existing.address = store_data['address']
                                    existing.city = store_data['city']
                                    updated += 1
                                    self.branch_mappings[chain_name][store_data['store_id']] = existing.branch_id
                                else:
                                    # Create new branch
                                    branch = Branch(
                                        chain_id=chain.chain_id,
                                        store_id=store_data['store_id'],
                                        name=store_data['store_name'],
                                        address=store_data['address'],
                                        city=store_data['city']
                                    )
                                    db.add(branch)
                                    db.flush()
                                    imported += 1
                                    self.branch_mappings[chain_name][store_data['store_id']] = branch.branch_id

                            except Exception as e:
                                logger.warning(f"Error processing store {store_data.get('store_id', 'unknown')}: {e}")
                                continue

                        # Commit batch
                        db.commit()
                        logger.info(f"Processed batch {i//batch_size + 1}/{(len(stores) + batch_size - 1)//batch_size}")

                        # Small delay between batches to avoid overwhelming Oracle
                        time.sleep(0.1)

                    logger.info(f"{chain_name}: Imported {imported} new stores, updated {updated} existing stores")
                    return imported + updated

            except (DatabaseError, DisconnectionError) as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Database error in import_stores (attempt {attempt + 1}), retrying: {e}")
                    time.sleep(2 ** attempt)
                    continue
                else:
                    logger.error(f"Failed to import stores after {max_retries} attempts: {e}")
                    return 0
            except Exception as e:
                logger.error(f"Unexpected error importing stores: {e}")
                return 0

    def import_prices(self, chain_name: str, prices: List[Dict[str, Any]]) -> int:
        """Import prices to database with enhanced error handling"""
        if not prices:
            logger.warning(f"No prices to import for {chain_name}")
            return 0

        max_retries = 3
        for attempt in range(max_retries):
            try:
                with get_db_with_retry() as db:
                    # Get chain
                    chain = db.query(Chain).filter(Chain.name == chain_name).first()
                    if not chain:
                        logger.error(f"Chain '{chain_name}' not found")
                        return 0

                    # Process in very small batches to avoid Oracle timeouts
                    batch_size = 25  # Very small batches for Oracle cloud
                    total_products = 0
                    total_prices = 0

                    for i in range(0, len(prices), batch_size):
                        batch = prices[i:i + batch_size]
                        batch_products, batch_prices = self._process_price_batch(db, chain.chain_id, batch)
                        total_products += batch_products
                        total_prices += batch_prices

                        # Commit after each small batch
                        db.commit()

                        if i % (batch_size * 10) == 0:  # Log progress every 250 records
                            logger.info(f"Processed {i + len(batch)}/{len(prices)} prices for {chain_name}")

                        # Small delay to prevent overwhelming Oracle
                        time.sleep(0.05)

                    logger.info(f"{chain_name}: Created {total_products} new products, processed {total_prices} prices")
                    return total_prices

            except (DatabaseError, DisconnectionError) as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Database error in import_prices (attempt {attempt + 1}), retrying: {e}")
                    time.sleep(2 ** attempt)
                    continue
                else:
                    logger.error(f"Failed to import prices after {max_retries} attempts: {e}")
                    return 0
            except Exception as e:
                logger.error(f"Unexpected error importing prices: {e}")
                return 0

    def _process_price_batch(self, db, chain_id: int, batch: List[Dict]) -> tuple:
        """Process a small batch of prices with individual error handling"""
        products_created = 0
        prices_processed = 0

        for price_data in batch:
            try:
                # Skip if missing required data
                if not price_data.get('store_id') or not price_data.get('barcode'):
                    continue

                store_id = price_data['store_id']
                if store_id not in self.branch_mappings.get(self._get_chain_name(chain_id), {}):
                    continue  # Skip if store not found

                branch_id = self.branch_mappings[self._get_chain_name(chain_id)][store_id]

                # Get or create chain product
                chain_product = db.query(ChainProduct).filter(
                    ChainProduct.chain_id == chain_id,
                    ChainProduct.barcode == price_data['barcode']
                ).first()

                if not chain_product:
                    chain_product = ChainProduct(
                        chain_id=chain_id,
                        barcode=price_data['barcode'],
                        name=price_data.get('name', f"Product {price_data['barcode']}")
                    )
                    db.add(chain_product)
                    db.flush()
                    products_created += 1

                # Update or create price
                existing_price = db.query(BranchPrice).filter(
                    BranchPrice.chain_product_id == chain_product.chain_product_id,
                    BranchPrice.branch_id == branch_id
                ).first()

                price_value = float(price_data['price'])

                if existing_price:
                    existing_price.price = price_value
                    existing_price.last_updated = datetime.utcnow()
                else:
                    branch_price = BranchPrice(
                        chain_product_id=chain_product.chain_product_id,
                        branch_id=branch_id,
                        price=price_value,
                        last_updated=datetime.utcnow()
                    )
                    db.add(branch_price)

                prices_processed += 1

            except Exception as e:
                logger.debug(f"Error processing individual price record: {e}")
                continue

        return products_created, prices_processed

    def _get_chain_name(self, chain_id: int) -> str:
        """Helper to get chain name from ID"""
        if chain_id == 1:
            return 'shufersal'
        elif chain_id == 2:
            return 'victory'
        else:
            return 'unknown'

    def import_chain_data(self, chain_name: str, include_prices: bool = False):
        """Import all data for a specific chain with resilience"""
        logger.info(f"\n{'='*50}")
        logger.info(f"Importing data for {chain_name.upper()}")
        logger.info(f"{'='*50}\n")

        try:
            # Get parser
            parser = get_parser(chain_name)

            # Import stores
            logger.info(f"📦 Fetching store data...")
            stores = parser.process_stores()

            if stores:
                logger.info(f"Found {len(stores)} stores")
                self.import_stores(chain_name, stores)
            else:
                logger.warning(f"No stores found for {chain_name}")
                return

            # Import prices if requested
            if include_prices:
                logger.info(f"\n💰 Fetching price data...")
                try:
                    prices = parser.process_prices(self.branch_mappings.get(chain_name, {}))

                    if prices:
                        logger.info(f"Found {len(prices)} prices")
                        # Import in smaller chunks for Oracle
                        chunk_size = 1000
                        for i in range(0, len(prices), chunk_size):
                            chunk = prices[i:i + chunk_size]
                            logger.info(f"Importing price chunk {i//chunk_size + 1}")
                            self.import_prices(chain_name, chunk)
                            time.sleep(1)  # Pause between chunks
                    else:
                        logger.warning(f"No prices found for {chain_name}")

                except Exception as e:
                    logger.error(f"Error fetching prices for {chain_name}: {e}")

        except Exception as e:
            logger.error(f"Error importing chain data for {chain_name}: {e}")

    def show_summary(self):
        """Show database summary with retry logic"""
        try:
            with get_db_with_retry() as db:
                logger.info("\n" + "="*50)
                logger.info("📊 DATABASE SUMMARY")
                logger.info("="*50 + "\n")

                # Chains and branches
                chains = db.query(Chain).all()
                for chain in chains:
                    branch_count = db.query(Branch).filter(Branch.chain_id == chain.chain_id).count()
                    product_count = db.query(ChainProduct).filter(ChainProduct.chain_id == chain.chain_id).count()

                    logger.info(f"{chain.display_name} ({chain.name}):")
                    logger.info(f"  - Branches: {branch_count}")
                    logger.info(f"  - Products: {product_count}")

                # Total statistics
                total_branches = db.query(Branch).count()
                total_products = db.query(ChainProduct).count()
                total_prices = db.query(BranchPrice).count()

                logger.info(f"\n📈 Totals:")
                logger.info(f"  - Total branches: {total_branches}")
                logger.info(f"  - Total products: {total_products}")
                logger.info(f"  - Total prices: {total_prices}")

        except Exception as e:
            logger.error(f"Error showing summary: {e}")


def main():
    """Main entry point with better error handling"""
    parser = argparse.ArgumentParser(description='Import chain data')
    parser.add_argument('--chain', type=str, help='Specific chain to import (default: all)')
    parser.add_argument('--stores-only', action='store_true', help='Import only stores, not prices')
    parser.add_argument('--list-chains', action='store_true', help='List available chains')

    args = parser.parse_args()

    if args.list_chains:
        print("\nAvailable chains:")
        for chain_name in PARSER_REGISTRY.keys():
            print(f"  - {chain_name}")
        return

    importer = ChainDataImporter()

    # Determine which chains to import
    chains_to_import = [args.chain] if args.chain else list(PARSER_REGISTRY.keys())

    # Import data
    for chain_name in chains_to_import:
        try:
            importer.import_chain_data(chain_name, include_prices=not args.stores_only)
        except Exception as e:
            logger.error(f"Failed to import {chain_name}: {e}")
            continue  # Continue with next chain

    # Show summary
    importer.show_summary()


if __name__ == "__main__":
    main()
