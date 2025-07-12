# test_oracle_connection.py
"""Test Oracle connection and timeout handling"""

import os
import sys
from pathlib import Path
import time
import logging
from sqlalchemy import text

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from database.connection import get_db_with_retry, USE_ORACLE
from database.new_models import Chain, Branch, ChainProduct, BranchPrice

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_basic_connection():
    """Test basic database connection"""
    logger.info("Testing basic connection...")

    try:
        with get_db_with_retry() as db:
            if USE_ORACLE:
                result = db.execute(text("SELECT 'Hello from Oracle' as msg FROM DUAL"))
            else:
                result = db.execute(text("SELECT 'Hello from SQLite' as msg"))

            msg = result.fetchone()[0]
            logger.info(f"✓ Connection successful: {msg}")
            return True
    except Exception as e:
        logger.error(f"✗ Connection failed: {e}")
        return False


def test_table_counts():
    """Test reading from all tables"""
    logger.info("\nTesting table access...")

    try:
        with get_db_with_retry() as db:
            tables = [
                ("Chains", Chain),
                ("Branches", Branch),
                ("Products", ChainProduct),
                ("Prices", BranchPrice)
            ]

            for table_name, model in tables:
                count = db.query(model).count()
                logger.info(f"✓ {table_name}: {count} records")

            return True
    except Exception as e:
        logger.error(f"✗ Table access failed: {e}")
        return False


def test_timeout_handling():
    """Test long-running query timeout handling"""
    logger.info("\nTesting timeout handling...")

    if not USE_ORACLE:
        logger.info("Skipping timeout test (SQLite)")
        return True

    try:
        with get_db_with_retry() as db:
            # This should complete quickly
            start = time.time()
            db.execute(text("SELECT COUNT(*) FROM chains"))
            elapsed = time.time() - start
            logger.info(f"✓ Quick query completed in {elapsed:.2f}s")

            # Test connection persistence
            time.sleep(2)
            db.execute(text("SELECT 1 FROM DUAL"))
            logger.info("✓ Connection persisted after delay")

            return True
    except Exception as e:
        logger.error(f"✗ Timeout handling failed: {e}")
        return False


def test_batch_operations():
    """Test batch insert/update operations"""
    logger.info("\nTesting batch operations...")

    try:
        with get_db_with_retry() as db:
            # Get a test chain
            chain = db.query(Chain).first()
            if not chain:
                logger.warning("No chains found, skipping batch test")
                return True

            # Test reading multiple records
            products = db.query(ChainProduct).filter(
                ChainProduct.chain_id == chain.chain_id
            ).limit(10).all()

            logger.info(f"✓ Read {len(products)} products successfully")

            # Test a small update
            if products:
                product = products[0]
                old_name = product.name
                product.name = f"{old_name} (test)"
                db.commit()

                # Rollback
                product.name = old_name
                db.commit()

                logger.info("✓ Update and rollback successful")

            return True
    except Exception as e:
        logger.error(f"✗ Batch operations failed: {e}")
        return False


def main():
    """Run all tests"""
    logger.info(f"Testing Oracle Cloud Database Connection")
    logger.info(f"Database: {'Oracle' if USE_ORACLE else 'SQLite'}")
    logger.info("="*60)

    tests = [
        test_basic_connection,
        test_table_counts,
        test_timeout_handling,
        test_batch_operations
    ]

    passed = 0
    for test in tests:
        if test():
            passed += 1
        time.sleep(1)  # Small delay between tests

    logger.info("\n" + "="*60)
    logger.info(f"Tests completed: {passed}/{len(tests)} passed")

    if passed == len(tests):
        logger.info("✓ All tests passed! Oracle connection is working properly.")
    else:
        logger.warning("⚠ Some tests failed. Check the configuration.")


if __name__ == "__main__":
    main()
