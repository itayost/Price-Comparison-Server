#!/usr/bin/env python3
"""
Diagnose price coverage issues
"""

from database.connection import SessionLocal
from database.new_models import Chain, Branch, ChainProduct, BranchPrice
from sqlalchemy import func
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def diagnose_price_coverage():
    """Diagnose why we have limited price coverage"""
    db = SessionLocal()

    try:
        logger.info("=== PRICE COVERAGE DIAGNOSIS ===")

        # 1. Check branches in Tel Aviv
        logger.info("\n1. Branches in Tel Aviv:")
        tel_aviv_branches = db.query(
            Branch.branch_id,
            Branch.store_id,
            Branch.name,
            Chain.display_name
        ).join(
            Chain
        ).filter(
            Branch.city == 'תל אביב'
        ).all()

        logger.info(f"Total branches in Tel Aviv: {len(tel_aviv_branches)}")

        # Group by chain
        by_chain = {}
        for branch in tel_aviv_branches:
            chain = branch.display_name
            if chain not in by_chain:
                by_chain[chain] = []
            by_chain[chain].append({
                'branch_id': branch.branch_id,
                'store_id': branch.store_id,
                'name': branch.name
            })

        for chain, branches in by_chain.items():
            logger.info(f"\n  {chain}: {len(branches)} branches")
            for b in branches[:5]:  # Show first 5
                logger.info(f"    - Branch ID: {b['branch_id']}, Store ID: {b['store_id']}, Name: {b['name']}")
            if len(branches) > 5:
                logger.info(f"    ... and {len(branches) - 5} more")

        # 2. Check price coverage for these branches
        logger.info("\n2. Price coverage by branch:")
        for chain, branches in by_chain.items():
            logger.info(f"\n  {chain}:")
            for branch in branches[:10]:  # Check first 10 branches
                price_count = db.query(func.count(BranchPrice.price_id)).filter(
                    BranchPrice.branch_id == branch['branch_id']
                ).scalar()
                logger.info(f"    - {branch['name']} (ID: {branch['branch_id']}): {price_count:,} prices")

        # 3. Check a specific product across all Tel Aviv branches
        logger.info("\n3. Sample product coverage (Tnuva Yogurt 7290000057132):")

        # Get the product
        product = db.query(ChainProduct).filter(
            ChainProduct.barcode == '7290000057132'
        ).first()

        if product:
            # Check how many Tel Aviv branches have this product
            branch_ids = [b.branch_id for b in tel_aviv_branches]

            prices_found = db.query(
                BranchPrice.branch_id,
                Branch.name,
                Chain.display_name,
                BranchPrice.price
            ).join(
                Branch, BranchPrice.branch_id == Branch.branch_id
            ).join(
                Chain, Branch.chain_id == Chain.chain_id
            ).filter(
                BranchPrice.chain_product_id == product.chain_product_id,
                Branch.branch_id.in_(branch_ids)
            ).all()

            logger.info(f"  Found in {len(prices_found)} out of {len(tel_aviv_branches)} Tel Aviv branches")
            logger.info("  Branches with this product:")
            for p in prices_found:
                logger.info(f"    - {p.display_name} - {p.name}: ₪{p.price}")

        # 4. Check for store_id issues
        logger.info("\n4. Store ID format check:")

        # Sample some store IDs
        sample_stores = db.query(Branch.store_id, Branch.name, Chain.name).join(Chain).limit(20).all()
        logger.info("  Sample store IDs in database:")
        for store in sample_stores:
            logger.info(f"    - Chain: {store[2]}, Store ID: '{store[0]}', Name: {store[1]}")

        # 5. Check total price import stats
        logger.info("\n5. Overall import statistics:")

        total_branches = db.query(func.count(Branch.branch_id)).scalar()
        branches_with_prices = db.query(func.count(func.distinct(BranchPrice.branch_id))).scalar()
        total_prices = db.query(func.count(BranchPrice.price_id)).scalar()
        total_products = db.query(func.count(ChainProduct.chain_product_id)).scalar()

        logger.info(f"  Total branches: {total_branches}")
        logger.info(f"  Branches with prices: {branches_with_prices} ({branches_with_prices/total_branches*100:.1f}%)")
        logger.info(f"  Total prices: {total_prices:,}")
        logger.info(f"  Total products: {total_products:,}")
        logger.info(f"  Avg prices per branch: {total_prices/branches_with_prices:.0f}")

        # 6. Check for recent imports
        logger.info("\n6. Recent price updates:")
        recent_prices = db.query(
            func.date(BranchPrice.last_updated),
            func.count(BranchPrice.price_id)
        ).group_by(
            func.date(BranchPrice.last_updated)
        ).order_by(
            func.date(BranchPrice.last_updated).desc()
        ).limit(5).all()

        for date, count in recent_prices:
            logger.info(f"  {date}: {count:,} prices")

    finally:
        db.close()


def check_import_logs():
    """Check import statistics from the last run"""
    logger.info("\n=== CHECKING IMPORT LOGS ===")
    logger.info("If you have import logs, check for:")
    logger.info("  - 'branches_skipped' count")
    logger.info("  - 'No store ID found' warnings")
    logger.info("  - 'Store not found' messages")
    logger.info("\nRun import with --debug flag for detailed logs:")
    logger.info("  python scripts/import_prices.py --limit 5 --debug")


if __name__ == "__main__":
    diagnose_price_coverage()
    check_import_logs()
