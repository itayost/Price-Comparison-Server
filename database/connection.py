# price_comparison_server/database/connection.py

import os
import logging
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool, QueuePool
from sqlalchemy.exc import DatabaseError, DisconnectionError
from contextlib import contextmanager
from typing import Generator
from dotenv import load_dotenv
import time

# Load environment variables
load_dotenv()

# Import models
from .new_models import Base, User, Chain, Branch, ChainProduct, BranchPrice, SavedCart

logger = logging.getLogger(__name__)

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL")
USE_ORACLE = os.getenv("USE_ORACLE", "false").lower() == "true"

# For Oracle with wallet
TNS_ADMIN = os.getenv("TNS_ADMIN") or os.getenv("ORACLE_WALLET_DIR", "./wallet")

if USE_ORACLE:
    # Oracle configuration
    wallet_dir = Path(TNS_ADMIN).resolve()
    os.environ['TNS_ADMIN'] = str(wallet_dir)

    # Build Oracle connection string
    ORACLE_USER = os.getenv("ORACLE_USER")
    ORACLE_PASSWORD = os.getenv("ORACLE_PASSWORD")
    ORACLE_DSN = os.getenv("ORACLE_DSN") or os.getenv("ORACLE_SERVICE", "champdb_low")

    # Enhanced connect args for Oracle
    connect_args = {
        "config_dir": str(wallet_dir),
        "wallet_location": str(wallet_dir),
        # Connection timeout settings (only supported parameters)
        "tcp_connect_timeout": 30,
        "retry_count": 3,
        "retry_delay": 1
    }

    # Add wallet password if provided
    wallet_password = os.getenv("ORACLE_WALLET_PASSWORD")
    if wallet_password:
        connect_args["wallet_password"] = wallet_password

    DATABASE_URL = f"oracle+oracledb://{ORACLE_USER}:{ORACLE_PASSWORD}@{ORACLE_DSN}"

    logger.info(f"Using Oracle database with TNS_ADMIN: {wallet_dir}")
    logger.info(f"Connecting to DSN: {ORACLE_DSN}")
else:
    # SQLite/PostgreSQL configuration
    if not DATABASE_URL:
        DATABASE_URL = "sqlite:///./price_comparison.db"
    logger.info(f"Using database: {DATABASE_URL}")

# Create engine with appropriate settings
try:
    if USE_ORACLE:
        # Oracle-specific engine configuration
        engine = create_engine(
            DATABASE_URL,
            # Use NullPool to avoid connection pooling issues with Oracle
            poolclass=NullPool,
            echo=os.getenv("SQL_ECHO", "false").lower() == "true",
            connect_args=connect_args,
            # Additional engine options for Oracle
            pool_pre_ping=True,  # Check connections before using
            pool_recycle=300,    # Recycle connections after 5 minutes
        )
    else:
        # SQLite/PostgreSQL engine
        engine = create_engine(
            DATABASE_URL,
            echo=os.getenv("SQL_ECHO", "false").lower() == "true",
            connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
            # Use standard pool for SQLite/PostgreSQL
            poolclass=QueuePool,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True
        )

    # Test connection with retry
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with engine.connect() as conn:
                if USE_ORACLE:
                    result = conn.execute(text("SELECT 1 FROM DUAL"))
                else:
                    result = conn.execute(text("SELECT 1"))
                result.fetchone()
                logger.info("✅ Database connection successful!")
                break
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Database connection attempt {attempt + 1} failed, retrying...")
                time.sleep(2 ** attempt)
            else:
                raise

except Exception as e:
    logger.error(f"❌ Database connection failed: {str(e)}")
    if USE_ORACLE:
        logger.error(f"TNS_ADMIN is set to: {os.environ.get('TNS_ADMIN')}")
        logger.error("Make sure wallet files are in the correct location")
    raise

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Get database session with automatic cleanup"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def get_db_with_retry(max_retries: int = 3) -> Generator[Session, None, None]:
    """Get database session with retry logic for Oracle timeouts"""
    last_error = None

    for attempt in range(max_retries):
        db = SessionLocal()
        try:
            # Test the connection
            if USE_ORACLE:
                db.execute(text("SELECT 1 FROM DUAL"))
            else:
                db.execute(text("SELECT 1"))

            yield db
            db.commit()
            return

        except (DatabaseError, DisconnectionError) as e:
            db.rollback()
            last_error = e
            logger.warning(f"Database error (attempt {attempt + 1}/{max_retries}): {str(e)[:100]}")

            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff

        except Exception as e:
            db.rollback()
            raise

        finally:
            db.close()

    # If we get here, all retries failed
    logger.error(f"All database retry attempts failed")
    raise last_error


def get_db_session():
    """FastAPI dependency for database sessions"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database tables"""
    try:
        logger.info("Initializing database tables...")

        if USE_ORACLE:
            logger.info("Using Oracle database...")

            # Drop tables if requested (careful!)
            if os.getenv("DROP_TABLES", "false").lower() == "true":
                logger.warning("Dropping existing tables...")
                Base.metadata.drop_all(bind=engine)

        # Create all tables
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Database tables created successfully!")

        # Create default chains with retry logic
        with get_db_with_retry() as db:
            existing_chains = db.query(Chain).count()
            if existing_chains == 0:
                logger.info("Creating default chains...")

                chains = [
                    Chain(name="shufersal", display_name="שופרסל"),
                    Chain(name="victory", display_name="ויקטורי")
                ]

                for chain in chains:
                    existing = db.query(Chain).filter(Chain.name == chain.name).first()
                    if not existing:
                        db.add(chain)
                        logger.info(f"Created chain: {chain.display_name}")

                db.commit()
                logger.info("✅ Default chains created!")

    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        raise


# Create a helper function for manual connection recovery
def recover_connection():
    """Attempt to recover a failed database connection"""
    global engine, SessionLocal

    logger.info("Attempting to recover database connection...")

    try:
        # Close existing engine
        engine.dispose()

        # Recreate engine
        if USE_ORACLE:
            wallet_dir = Path(TNS_ADMIN).resolve()
            connect_args = {
                "config_dir": str(wallet_dir),
                "wallet_location": str(wallet_dir),
                "tcp_connect_timeout": 30,
                "retry_count": 3,
                "retry_delay": 1
            }

            wallet_password = os.getenv("ORACLE_WALLET_PASSWORD")
            if wallet_password:
                connect_args["wallet_password"] = wallet_password

            engine = create_engine(
                DATABASE_URL,
                poolclass=NullPool,
                echo=os.getenv("SQL_ECHO", "false").lower() == "true",
                connect_args=connect_args,
                pool_pre_ping=True,
                pool_recycle=300,
            )
        else:
            engine = create_engine(
                DATABASE_URL,
                echo=os.getenv("SQL_ECHO", "false").lower() == "true",
                connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
                poolclass=QueuePool,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True
            )

        # Recreate session factory
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        # Test connection
        with engine.connect() as conn:
            if USE_ORACLE:
                conn.execute(text("SELECT 1 FROM DUAL"))
            else:
                conn.execute(text("SELECT 1"))

        logger.info("✅ Database connection recovered!")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to recover connection: {e}")
        return False


if __name__ == "__main__":
    # Initialize database when run directly
    init_db()
