#!/usr/bin/env python3
# test_import.py - Test the import process with monitoring

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

import logging
import time
from datetime import datetime

# Configure logging with more detail
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f'import_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    ]
)

logger = logging.getLogger(__name__)


def test_database_connection():
    """Test database connection before import"""
    logger.info("Testing database connection...")

    try:
        from database.connection import get_db_with_retry
        from database.new_models import Chain, Branch

        with get_db_with_retry() as db:
            # Test basic queries
            chains = db.query(Chain).count()
            branches = db.query(Branch).count()

            logger.info(f"✅ Database connected successfully!")
            logger.info(f"   - Found {chains} chains")
            logger.info(f"   - Found {branches} branches")

            if branches == 0:
                logger.warning("⚠️  No branches found! Make sure to import stores first:")
                logger.warning("   python scripts/import_chain_data.py --stores-only")
                return False

            return True

    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        return False


def import_with_monitoring(chain='shufersal', limit=5):
    """Run import with progress monitoring"""
    logger.info(f"\n{'='*60}")
    logger.info(f"Starting test import for {chain} (limit: {limit} files)")
    logger.info(f"{'='*60}\n")

    # Test connection first
    if not test_database_connection():
        logger.error("Cannot proceed without database connection")
        return

    try:
        # Import the fixed importer
        from scripts.import_prices import PriceImporter

        importer = PriceImporter()

        # Set up progress monitoring
        start_time = time.time()
        last_log_time = start_time

        # Custom progress logger
        original_log_progress = importer.log_progress

        def enhanced_log_progress():
            nonlocal last_log_time
            current_time = time.time()
            elapsed = current_time - start_time
            since_last = current_time - last_log_time

            logger.info(f"\n{'='*50}")
            logger.info(f"PROGRESS UPDATE (Elapsed: {elapsed:.1f}s)")
            logger.info(f"{'='*50}")
            original_log_progress()

            # Calculate rates
            if importer.stats['files_processed'] > 0:
                files_per_minute = importer.stats['files_processed'] / (elapsed / 60)
                logger.info(f"  Processing rate: {files_per_minute:.1f} files/minute")

            if importer.stats['prices_created'] + importer.stats['prices_updated'] > 0:
                total_prices = importer.stats['prices_created'] + importer.stats['prices_updated']
                prices_per_second = total_prices / elapsed
                logger.info(f"  Price rate: {prices_per_second:.1f} prices/second")

            logger.info(f"  Time since last update: {since_last:.1f}s")
            last_log_time = current_time

        importer.log_progress = enhanced_log_progress

        # Run the import
        importer.import_chain_prices(chain, limit)

        # Final summary
        total_time = time.time() - start_time
        logger.info(f"\n{'='*60}")
        logger.info(f"IMPORT COMPLETED")
        logger.info(f"{'='*60}")
        logger.info(f"Total time: {total_time:.1f} seconds ({total_time/60:.1f} minutes)")

        importer.show_summary()

        # Check for issues
        if importer.stats['errors'] > 0:
            logger.warning(f"\n⚠️  Import completed with {importer.stats['errors']} errors")
        else:
            logger.info("\n✅ Import completed successfully with no errors!")

        if importer.stats['branches_skipped'] > 0:
            logger.info(f"\n📝 Note: {importer.stats['branches_skipped']} price entries were skipped")
            logger.info("   This is normal if some stores haven't been imported yet")

    except KeyboardInterrupt:
        logger.info("\n\n⚠️  Import interrupted by user")
        raise
    except Exception as e:
        logger.error(f"\n❌ Import failed with error: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Main function with argument parsing"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Test import script with monitoring',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test with 5 Shufersal files
  python test_import.py

  # Test with 10 Victory files
  python test_import.py --chain victory --limit 10

  # Test with all files (careful!)
  python test_import.py --chain all --limit 0

  # Enable debug logging
  python test_import.py --debug
        """
    )

    parser.add_argument('--chain',
                       choices=['shufersal', 'victory', 'all'],
                       default='shufersal',
                       help='Chain to test (default: shufersal)')

    parser.add_argument('--limit',
                       type=int,
                       default=5,
                       help='Number of files to process (default: 5, use 0 for all)')

    parser.add_argument('--debug',
                       action='store_true',
                       help='Enable debug logging')

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Show configuration
    logger.info("Import Test Configuration:")
    logger.info(f"  Chain: {args.chain}")
    logger.info(f"  File limit: {args.limit if args.limit > 0 else 'No limit'}")
    logger.info(f"  Debug mode: {'ON' if args.debug else 'OFF'}")
    logger.info("")

    try:
        if args.chain == 'all':
            for chain in ['shufersal', 'victory']:
                import_with_monitoring(chain, args.limit)
                logger.info(f"\n{'='*60}\n")
        else:
            import_with_monitoring(args.chain, args.limit)

    except KeyboardInterrupt:
        logger.info("\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\nTest failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
