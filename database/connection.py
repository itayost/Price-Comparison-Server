# database/connection_optimized.py

import os
import logging
import time
from pathlib import Path
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool, NullPool
from sqlalchemy.exc import DatabaseError, DisconnectionError, OperationalError
from contextlib import contextmanager
from typing import Generator
import oracledb
from dotenv import load_dotenv
import threading
from functools import wraps

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Import models
from .new_models import Base, User, Chain, Branch, ChainProduct, BranchPrice, SavedCart

# Oracle configuration
USE_ORACLE = os.getenv("USE_ORACLE", "false").lower() == "true"

class OracleConnectionManager:
    """Manages Oracle connections with resilience and optimization"""

    def __init__(self):
        self.wallet_dir = Path(os.getenv("TNS_ADMIN") or os.getenv("ORACLE_WALLET_DIR", "./wallet")).resolve()
        self.pool = None
        self._lock = threading.Lock()

    def create_pool(self):
        """Create Oracle native connection pool"""
        if self.pool:
            return self.pool

        with self._lock:
            if self.pool:  # Double-check
                return self.pool

            logger.info("Creating Oracle connection pool...")

            params = oracledb.PoolParams(
                user=os.getenv("ORACLE_USER"),
                password=os.getenv("ORACLE_PASSWORD"),
                dsn=os.getenv("ORACLE_SERVICE", "champdb_low"),
                config_dir=str(self.wallet_dir),
                wallet_location=str(self.wallet_dir),
                wallet_password=os.getenv("ORACLE_WALLET_PASSWORD"),
                min=2,
                max=20,
                increment=2,
                ping_interval=60,  # Keep connections alive
                timeout=1800,      # 30 min idle timeout
                max_lifetime_session=3600,  # 1 hour max lifetime
                getmode=oracledb.POOL_GETMODE_WAIT
            )

            self.pool = oracledb.create_pool_async(**params)
            logger.info(f"Oracle pool created: min={params.min}, max={params.max}")

            return self.pool

# Global connection manager
oracle_manager = OracleConnectionManager() if USE_ORACLE else None

def exponential_backoff_retry(max_retries=3, base_delay=1, max_delay=60):
    """Decorator for exponential backoff retry"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (OperationalError, DisconnectionError, DatabaseError) as e:
                    last_exception = e
                    if attempt == max_retries - 1:
                        raise

                    delay = min(base_delay * (2 ** attempt), max_delay)
                    jitter = delay * 0.1 * (0.5 - threading.current_thread().ident % 10 / 10)

                    logger.warning(f"Retry {attempt + 1}/{max_retries} after {delay:.1f}s: {str(e)[:100]}")
                    time.sleep(delay + jitter)

            raise last_exception

        return wrapper
    return decorator

# Create optimized engine
if USE_ORACLE:
    # Set TNS_ADMIN
    os.environ['TNS_ADMIN'] = str(oracle_manager.wallet_dir)

    # Create engine with proper pooling
    engine = create_engine(
        f"oracle+oracledb://{os.getenv('ORACLE_USER')}:{os.getenv('ORACLE_PASSWORD')}@{os.getenv('ORACLE_SERVICE')}",

        # Use QueuePool for better performance
        poolclass=QueuePool,
        pool_size=10,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=1800,  # 30 minutes
        pool_pre_ping=True,

        # Oracle optimizations
        connect_args={
        "config_dir": str(oracle_manager.wallet_dir),
        "wallet_location": str(oracle_manager.wallet_dir),
        "wallet_password": os.getenv("ORACLE_WALLET_PASSWORD"),
},

        # Engine options
        echo=os.getenv("SQL_ECHO", "false").lower() == "true",
        future=True,

        # Execution options
        execution_options={
            "stream_results": True,
            "max_row_buffer": 10000,
        }
    )

    # Add event listeners for connection lifecycle
    @event.listens_for(engine, "connect")
    def set_oracle_params(dbapi_connection, connection_record):
        """Set Oracle-specific parameters on connect"""
        with dbapi_connection.cursor() as cursor:
            # Enable auto-commit for better performance
            #cursor.execute("ALTER SESSION SET COMMIT_WRITE = BATCH,NOWAIT")
            # Increase array fetch size
            cursor.arraysize = 1000

else:
    # SQLite configuration remains the same
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./price_comparison.db")
    engine = create_engine(
        DATABASE_URL,
        echo=os.getenv("SQL_ECHO", "false").lower() == "true",
        connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
        poolclass=QueuePool,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True
    )

# Create session factory with optimizations
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False  # Important for performance
)

@contextmanager
def get_db_optimized() -> Generator[Session, None, None]:
    """Get database session with Oracle optimizations"""
    session = SessionLocal()

    try:
        if USE_ORACLE:
            # Set session parameters for bulk operations
            #session.execute(text("ALTER SESSION ENABLE PARALLEL DML"))
            #session.execute(text("ALTER SESSION SET \"_optimizer_use_feedback\" = FALSE"))
            pass

        yield session
        session.commit()

    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()

@contextmanager
@exponential_backoff_retry(max_retries=3)
def get_db_with_retry() -> Generator[Session, None, None]:
    """Get database session with automatic retry"""
    with get_db_optimized() as session:
        yield session

get_db = get_db_optimized

def get_db_session():
    """FastAPI dependency for database sessions"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Add init_db function
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

        return True

    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        raise

# Export all the names that other modules expect
__all__ = [
    'engine',
    'SessionLocal',
    'get_db',
    'get_db_session',
    'get_db_optimized',
    'get_db_with_retry',
    'USE_ORACLE',
    'init_db',
    'Base'
]
