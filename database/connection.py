# database/connection.py
"""Enhanced database connection with Oracle timeout handling"""

import os
import logging
from pathlib import Path
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool, QueuePool
from sqlalchemy.exc import DatabaseError, DisconnectionError, OperationalError
from contextlib import contextmanager
from typing import Generator
from dotenv import load_dotenv
import time

# Load environment variables
load_dotenv()

# Import models - but only after engine is created
# This will be done at the bottom of the file

logger = logging.getLogger(__name__)

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL")
USE_ORACLE = os.getenv("USE_ORACLE", "false").lower() == "true"

# Initialize engine and SessionLocal as None
engine = None
SessionLocal = None

# For Oracle with wallet
TNS_ADMIN = os.getenv("TNS_ADMIN") or os.getenv("ORACLE_WALLET_DIR", "./wallet")

def create_database_engine():
    """Create and return the database engine"""
    global engine, SessionLocal

    if USE_ORACLE:
        try:
            import oracledb

            # Oracle configuration
            wallet_dir = Path(TNS_ADMIN).resolve()

            # Ensure wallet directory exists
            if not wallet_dir.exists():
                raise FileNotFoundError(f"Oracle wallet directory not found: {wallet_dir}")

            os.environ['TNS_ADMIN'] = str(wallet_dir)

            # Configure oracledb defaults BEFORE creating connection
            oracledb.defaults.config_dir = str(wallet_dir)
            oracledb.defaults.tcp_connect_timeout = 30.0
            oracledb.defaults.call_timeout = 60000  # 60 seconds
            oracledb.defaults.prefetchrows = 100
            oracledb.defaults.arraysize = 100

            logger.info(f"Oracle wallet directory: {wallet_dir}")

        except ImportError:
            logger.error("oracledb not installed. Install with: pip install oracledb")
            raise

        # Build Oracle connection string
        ORACLE_USER = os.getenv("ORACLE_USER")
        ORACLE_PASSWORD = os.getenv("ORACLE_PASSWORD")
        ORACLE_DSN = os.getenv("ORACLE_DSN") or os.getenv("ORACLE_SERVICE", "champdb_low")

        if not all([ORACLE_USER, ORACLE_PASSWORD]):
            raise ValueError("ORACLE_USER and ORACLE_PASSWORD must be set in .env file")

        # Connect args for Oracle
        connect_args = {
            "config_dir": str(wallet_dir),
            "wallet_location": str(wallet_dir),
        }

        # Add wallet password if provided
        wallet_password = os.getenv("ORACLE_WALLET_PASSWORD")
        if wallet_password:
            connect_args["wallet_password"] = wallet_password

        DATABASE_URL = f"oracle+oracledb://{ORACLE_USER}:{ORACLE_PASSWORD}@{ORACLE_DSN}"

        logger.info(f"Using Oracle database with TNS_ADMIN: {wallet_dir}")
        logger.info(f"Connecting to DSN: {ORACLE_DSN}")

        # Create engine with minimal configuration first
        try:
            engine = create_engine(
                DATABASE_URL,
                poolclass=NullPool,  # No connection pooling for Oracle
                connect_args=connect_args,
                echo=os.getenv("SQL_ECHO", "false").lower() == "true"
            )
        except Exception as e:
            logger.error(f"Failed to create Oracle engine: {e}")
            raise

    else:
        # SQLite/PostgreSQL configuration
        if not DATABASE_URL:
            DATABASE_URL = "sqlite:///./price_comparison.db"

        logger.info(f"Using database: {DATABASE_URL}")

        engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            echo=os.getenv("SQL_ECHO", "false").lower() == "true"
        )

    # Create session factory
    SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False
    )

    return engine, SessionLocal


def test_engine_connection(engine):
    """Test the engine connection"""
    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        try:
            with engine.connect() as conn:
                if USE_ORACLE:
                    result = conn.execute(text("SELECT 1 FROM DUAL"))
                else:
                    result = conn.execute(text("SELECT 1"))
                result.fetchone()
                logger.info("Database connection test successful")
                return True
        except Exception as e:
            retry_count += 1
            if retry_count < max_retries:
                logger.warning(f"Connection test failed (attempt {retry_count}/{max_retries}): {str(e)[:100]}")
                time.sleep(2 ** retry_count)
            else:
                logger.error(f"Connection test failed after {max_retries} attempts: {e}")
                raise
    return False


# Create engine and session factory
try:
    engine, SessionLocal = create_database_engine()

    # Only test connection if not in import phase
    if os.getenv("SKIP_DB_TEST", "false").lower() != "true":
        test_engine_connection(engine)

except Exception as e:
    logger.error(f"Failed to initialize database: {e}")
    # Don't raise during import - allow the module to load
    if os.getenv("TESTING", "false").lower() == "true":
        raise


def get_db() -> Generator[Session, None, None]:
    """Get database session"""
    if not SessionLocal:
        raise RuntimeError("Database not initialized. Call create_database_engine() first.")

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """Context manager for database session"""
    if not SessionLocal:
        raise RuntimeError("Database not initialized. Call create_database_engine() first.")

    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db_session():
    """Dependency for FastAPI routes"""
    if not SessionLocal:
        raise RuntimeError("Database not initialized. Call create_database_engine() first.")

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_with_retry(max_retries: int = 3) -> Generator[Session, None, None]:
    """Get database session with retry logic for Oracle timeouts"""
    if not SessionLocal:
        raise RuntimeError("Database not initialized. Call create_database_engine() first.")

    retry_count = 0
    last_error = None

    while retry_count < max_retries:
        db = None
        try:
            db = SessionLocal()
            # Test connection
            if USE_ORACLE:
                db.execute(text("SELECT 1 FROM DUAL"))
            else:
                db.execute(text("SELECT 1"))

            yield db
            return

        except (DatabaseError, DisconnectionError, OperationalError) as e:
            retry_count += 1
            last_error = e

            if db:
                db.close()

            if retry_count < max_retries:
                wait_time = 2 ** (retry_count - 1)  # Exponential backoff
                logger.warning(f"Database connection failed (attempt {retry_count}/{max_retries}), "
                              f"retrying in {wait_time}s: {str(e)[:100]}")
                time.sleep(wait_time)

                # Dispose of the engine pool to force new connections
                if engine:
                    engine.dispose()
            else:
                logger.error(f"Database connection failed after {max_retries} attempts")
                raise last_error


def init_db():
    """Initialize database tables"""
    if not engine:
        logger.error("Cannot initialize database - engine not created")
        return

    try:
        # Import models here to avoid circular imports
        from .new_models import Base, Chain, Branch, ChainProduct, BranchPrice, User, SavedCart

        logger.info("Creating database tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")

        # Test each table
        with get_db_context() as db:
            for table_name, model in [
                ("chains", Chain),
                ("branches", Branch),
                ("chain_products", ChainProduct),
                ("branch_prices", BranchPrice),
                ("users", User),
                ("saved_carts", SavedCart)
            ]:
                try:
                    count = db.query(model).count()
                    logger.info(f"Table {table_name}: {count} records")
                except Exception as e:
                    logger.warning(f"Could not query table {table_name}: {e}")

    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        if os.getenv("TESTING", "false").lower() == "true":
            raise


def test_connection():
    """Test database connection"""
    try:
        with get_db_with_retry() as db:
            if USE_ORACLE:
                result = db.execute(text("SELECT 'Connected to Oracle' as status FROM DUAL"))
            else:
                result = db.execute(text("SELECT 'Connected to SQLite' as status"))

            row = result.fetchone()
            logger.info(f"Database test: {row[0]}")
            return True

    except Exception as e:
        logger.error(f"Database connection test failed: {e}")
        return False


# Import models after engine is created
if engine:
    from .new_models import Base, User, Chain, Branch, ChainProduct, BranchPrice, SavedCart


# Initialize database on module import if not testing
if os.getenv("TESTING", "false").lower() != "true" and os.getenv("SKIP_DB_INIT", "false").lower() != "true":
    try:
        if engine:
            init_db()
    except Exception as e:
        logger.warning(f"Could not initialize database on import: {e}")


if __name__ == "__main__":
    # Test connection when run directly
    import sys

    # Set environment to skip import-time tests
    os.environ["SKIP_DB_TEST"] = "false"

    logger.info("Testing database connection...")

    # Recreate engine for testing
    try:
        engine, SessionLocal = create_database_engine()

        if test_connection():
            logger.info("Connection successful!")

            # Import models
            from .new_models import Chain, Branch, ChainProduct, BranchPrice, User, SavedCart

            # Show table counts
            with get_db_context() as db:
                logger.info("\nTable counts:")
                for model_name, model in [
                    ("Chains", Chain),
                    ("Branches", Branch),
                    ("Products", ChainProduct),
                    ("Prices", BranchPrice),
                    ("Users", User),
                    ("Saved carts", SavedCart)
                ]:
                    try:
                        count = db.query(model).count()
                        logger.info(f"{model_name}: {count}")
                    except Exception as e:
                        logger.error(f"Error querying {model_name}: {e}")
        else:
            logger.error("Connection failed!")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Failed to test connection: {e}")
        sys.exit(1)
