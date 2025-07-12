# database/startup.py
"""Database startup manager - handles initialization, checks, and data import"""

import os
import logging
from datetime import datetime
from sqlalchemy import text, func
from typing import Dict, Tuple
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from .connection import engine, get_db_optimized, get_db_with_retry, USE_ORACLE, init_db
from .new_models import Chain, Branch, ChainProduct, BranchPrice, User, SavedCart

logger = logging.getLogger(__name__)


class DatabaseStartup:
    """Manages database initialization and health checks"""

    def __init__(self):
        self.required_tables = ['chains', 'branches', 'chain_products', 'branch_prices', 'users', 'saved_carts']
        self.required_sequences = ['chain_id_seq', 'branch_id_seq', 'chain_product_id_seq',
                                  'price_id_seq', 'user_id_seq', 'cart_id_seq']

    def check_database_health(self) -> Dict[str, any]:
        """Check if database is properly initialized with data"""
        health = {
            'initialized': False,
            'tables_exist': False,
            'has_data': False,
            'needs_import': False,
            'details': {}
        }

        try:
            with engine.connect() as conn:
                # Check if tables exist
                if USE_ORACLE:
                    result = conn.execute(text("""
                        SELECT COUNT(*) FROM user_tables
                        WHERE UPPER(table_name) IN ('CHAINS', 'BRANCHES', 'CHAIN_PRODUCTS',
                                                    'BRANCH_PRICES', 'USERS', 'SAVED_CARTS')
                    """))
                    table_count = result.scalar()
                    health['tables_exist'] = table_count >= 6
                else:
                    # For SQLite/PostgreSQL
                    from sqlalchemy import inspect
                    inspector = inspect(engine)
                    existing_tables = inspector.get_table_names()
                    health['tables_exist'] = all(table in existing_tables for table in self.required_tables)

                if not health['tables_exist']:
                    health['needs_import'] = True
                    return health

                # Check data existence
                with get_db_optimized() as db:
                    health['details'] = {
                        'chains': db.query(func.count(Chain.chain_id)).scalar(),
                        'branches': db.query(func.count(Branch.branch_id)).scalar(),
                        'products': db.query(func.count(ChainProduct.chain_product_id)).scalar(),
                        'prices': db.query(func.count(BranchPrice.price_id)).scalar(),
                        'users': db.query(func.count(User.user_id)).scalar(),
                    }

                    # Check if we have basic data
                    health['has_data'] = (
                        health['details']['chains'] >= 2 and  # At least Shufersal and Victory
                        health['details']['branches'] > 0 and
                        health['details']['products'] > 0
                    )

                    health['initialized'] = health['tables_exist']
                    health['needs_import'] = not health['has_data']

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            health['error'] = str(e)
            health['needs_import'] = True

        return health

    def initialize_if_needed(self) -> bool:
        """Initialize database if needed"""
        health = self.check_database_health()

        if not health['tables_exist']:
            logger.info("Database tables not found. Initializing...")
            try:
                init_db()
                logger.info("✅ Database initialized successfully")
                return True
            except Exception as e:
                logger.error(f"❌ Failed to initialize database: {e}")
                raise
        else:
            logger.info("✅ Database tables already exist")
            return False

    def check_data_status(self) -> Tuple[bool, Dict[str, int]]:
        """Check if data needs to be imported"""
        health = self.check_database_health()

        if health['needs_import']:
            logger.info("📊 Database needs data import")
            if 'details' in health:
                for table, count in health['details'].items():
                    logger.info(f"  - {table}: {count} records")
            return True, health.get('details', {})
        else:
            logger.info("✅ Database has data")
            return False, health.get('details', {})

    def startup(self) -> Dict[str, any]:
        """Complete startup process"""
        logger.info("\n" + "="*60)
        logger.info("DATABASE STARTUP CHECK")
        logger.info("="*60)

        # 1. Initialize if needed
        initialized = self.initialize_if_needed()

        # 2. Check data status
        needs_import, data_counts = self.check_data_status()

        # 3. Import data if needed
        if needs_import and os.getenv("AUTO_IMPORT", "false").lower() == "true":
            logger.info("\n🔄 AUTO_IMPORT is enabled. Starting data import...")
            try:
                # Fix import paths
                import sys
                from pathlib import Path
                project_root = Path(__file__).parent.parent
                if str(project_root) not in sys.path:
                    sys.path.insert(0, str(project_root))

                from scripts.import_chain_data import ChainDataImporter
                from scripts.import_prices import PriceImporter

                # Import stores first
                logger.info("\n📦 Importing store data...")
                store_importer = ChainDataImporter()
                for chain in ['shufersal', 'victory']:
                    logger.info(f"  Importing {chain} stores...")
                    store_importer.import_chain_data(chain, include_prices=False)

                # Import prices
                logger.info("\n💰 Importing price data...")
                price_importer = PriceImporter()
                limit = int(os.getenv("IMPORT_LIMIT", "0")) or None

                if limit:
                    logger.info(f"  Limiting to {limit} files per chain for testing")

                for chain in ['shufersal', 'victory']:
                    logger.info(f"  Importing {chain} prices...")
                    price_importer.import_chain_prices(chain, limit_files=limit)

                logger.info("\n✅ Data import completed!")

            except ImportError as e:
                logger.error(f"❌ Import error: {e}")
                logger.info("\nMake sure you're running from the project root directory")
                logger.info("\nManual import commands:")
                logger.info("  python scripts/import_chain_data.py --stores-only")
                logger.info("  python scripts/import_prices.py")
            except Exception as e:
                logger.error(f"❌ Auto-import failed: {e}")
                import traceback
                traceback.print_exc()
                logger.info("\nYou can manually import data by running:")
                logger.info("  python scripts/import_chain_data.py --stores-only")
                logger.info("  python scripts/import_prices.py")

        elif needs_import:
            logger.info("\n⚠️  Database needs data. To import automatically, set AUTO_IMPORT=true in .env")
            logger.info("\nOr manually run:")
            logger.info("  python scripts/import_chain_data.py --stores-only")
            logger.info("  python scripts/import_prices.py")

        # 4. Final status
        final_health = self.check_database_health()

        logger.info("\n" + "-"*60)
        logger.info("STARTUP COMPLETE")
        logger.info("-"*60)
        logger.info(f"✅ Tables exist: {final_health['tables_exist']}")
        logger.info(f"✅ Has data: {final_health['has_data']}")

        if final_health['has_data'] and 'details' in final_health:
            logger.info("\nData summary:")
            for table, count in final_health['details'].items():
                if count > 0:
                    logger.info(f"  - {table}: {count:,}")

        logger.info("="*60 + "\n")

        return final_health


# Singleton instance
_startup_manager = None

def get_startup_manager() -> DatabaseStartup:
    """Get or create the startup manager"""
    global _startup_manager
    if _startup_manager is None:
        _startup_manager = DatabaseStartup()
    return _startup_manager


def ensure_database_ready():
    """Ensure database is ready - call this from main.py"""
    manager = get_startup_manager()
    return manager.startup()
