# main.py
"""Main FastAPI application with automatic database setup and scheduled price updates"""
import os
import sys
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import func, distinct
from datetime import datetime, timedelta
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import threading

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import database functions
from database.connection import engine, get_db_optimized, get_db_with_retry, USE_ORACLE, init_db
from database.new_models import Chain, Branch, ChainProduct, BranchPrice

# Import routers
from routes import auth_routes, cart_routes, product_routes, saved_carts_routes, system_routes

# Global scheduler instance
scheduler = BackgroundScheduler()

def ensure_database_ready():
    """Ensure database is initialized and check data status"""
    try:
        # Initialize database tables
        init_db()

        # Check if we have data
        with get_db_with_retry() as db:
            chains = db.query(Chain).count()
            branches = db.query(Branch).count()
            products = db.query(ChainProduct).count()
            prices = db.query(BranchPrice).count()

            has_data = chains > 0 and branches > 0 and products > 0 and prices > 0

            logger.info(f"Database status: Chains={chains}, Branches={branches}, Products={products}, Prices={prices}")

            return {
                'connected': True,
                'has_data': has_data,
                'chains': chains,
                'branches': branches,
                'products': products,
                'prices': prices
            }
    except Exception as e:
        logger.error(f"Database check failed: {e}")
        return {
            'connected': False,
            'has_data': False,
            'error': str(e)
        }

def print_database_summary():
    """Print a concise summary of database contents"""
    try:
        with get_db_with_retry() as db:
            # Print header
            print("\n" + "="*60)
            print("📊 Database Summary")
            print("="*60)

            # Basic counts
            chains = db.query(Chain).count()
            branches = db.query(Branch).count()
            products = db.query(ChainProduct).count()
            prices = db.query(BranchPrice).count()

            print(f"\n• Chains: {chains}")
            print(f"• Branches: {branches:,}")
            print(f"• Products: {products:,}")
            print(f"• Price records: {prices:,}")

            # Last update
            last_update = db.query(func.max(BranchPrice.last_updated)).scalar()
            if last_update:
                print(f"\n• Last update: {last_update.strftime('%Y-%m-%d %H:%M:%S')}")

            print("\n" + "="*60)
            print("✅ Server ready!")
            print("="*60 + "\n")

    except Exception as e:
        logger.error(f"Failed to print summary: {e}")

def update_prices_job():
    """Job to update prices from all chains"""
    logger.info("\n" + "="*60)
    logger.info("🔄 Starting scheduled price update...")
    logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*60)

    try:
        # Fix import paths
        project_root = Path(__file__).parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from scripts.import_prices import OptimizedPriceImporter

        # Create importer instance
        importer = OptimizedPriceImporter()

        # Get limit from environment (0 means no limit)
        limit = int(os.getenv("SCHEDULED_IMPORT_LIMIT", "0")) or None

        # Update prices for each chain
        chains = ['shufersal', 'victory']
        total_start = datetime.now()

        for chain in chains:
            try:
                logger.info(f"\n📦 Updating prices for {chain}...")
                chain_start = datetime.now()

                # Run the import
                importer.import_chain_prices(chain, limit_files=limit)

                chain_duration = (datetime.now() - chain_start).total_seconds()
                logger.info(f"✅ {chain} update completed in {chain_duration:.1f} seconds")

            except Exception as e:
                logger.error(f"❌ Failed to update {chain} prices: {e}")
                import traceback
                traceback.print_exc()

        # Print summary
        total_duration = (datetime.now() - total_start).total_seconds()
        logger.info(f"\n✅ Price update job completed in {total_duration:.1f} seconds")

        # Show updated statistics
        with get_db_with_retry() as db:
            total_prices = db.query(func.count(BranchPrice.price_id)).scalar()
            recent_updates = db.query(func.count(BranchPrice.price_id)).filter(
                BranchPrice.last_updated >= datetime.now() - timedelta(hours=1)
            ).scalar()

            logger.info(f"📊 Total prices in database: {total_prices:,}")
            logger.info(f"🔄 Prices updated in this run: {recent_updates:,}")

    except Exception as e:
        logger.error(f"❌ Price update job failed: {e}")
        import traceback
        traceback.print_exc()

    logger.info("="*60 + "\n")

def setup_scheduler():
    """Setup the background scheduler for periodic tasks"""
    # Check if scheduler is enabled
    if os.getenv("ENABLE_SCHEDULER", "true").lower() != "true":
        logger.info("⏸️  Scheduler is disabled (ENABLE_SCHEDULER=false)")
        return

    # Get interval from environment (default 60 minutes)
    interval_minutes = int(os.getenv("PRICE_UPDATE_INTERVAL", "60"))

    # Add the price update job
    scheduler.add_job(
        func=update_prices_job,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id='price_update_job',
        name='Update prices from all chains',
        replace_existing=True,
        misfire_grace_time=300  # 5 minutes grace time
    )

    # Start the scheduler
    scheduler.start()

    logger.info(f"⏰ Scheduler started - prices will update every {interval_minutes} minutes")

    # Check if we should run immediately on startup
    if os.getenv("RUN_UPDATE_ON_STARTUP", "false").lower() == "true":
        logger.info("🚀 Running initial price update...")
        # Run in a separate thread to not block startup
        threading.Thread(target=update_prices_job, daemon=True).start()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events"""
    # Startup
    logger.info("🚀 Starting Price Comparison Server...")

    try:
        # Ensure database is ready
        health = ensure_database_ready()

        if not health['connected']:
            logger.error("❌ Failed to connect to database!")
        elif not health['has_data']:
            logger.warning("⚠️  Server starting without price data!")
            logger.warning("   API will work but price comparisons will return no results")
            logger.warning("   Run import scripts or set AUTO_IMPORT=true in .env")
        else:
            logger.info(f"✅ Database ready with {health['products']:,} products and {health['prices']:,} prices")

            # Print detailed summary
            print_database_summary()

        # Setup scheduler for periodic updates
        setup_scheduler()

    except Exception as e:
        logger.error(f"❌ Startup failed: {e}")
        # Decide if you want to fail or continue
        # raise  # Uncomment to prevent server start on DB issues

    yield

    # Shutdown
    logger.info("👋 Shutting down Price Comparison Server...")

    # Shutdown scheduler
    if scheduler.running:
        logger.info("⏰ Stopping scheduler...")
        scheduler.shutdown(wait=True)

# Create FastAPI app
app = FastAPI(
    title="Price Comparison API",
    description="Compare grocery prices across different supermarket chains in Israel",
    version="2.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_routes.router)
app.include_router(cart_routes.router)
app.include_router(product_routes.router)
app.include_router(saved_carts_routes.router)
app.include_router(system_routes.router)

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Price Comparison API",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/api/system/health",
        "scheduler": {
            "enabled": scheduler.running if 'scheduler' in globals() else False,
            "next_run": str(scheduler.get_job('price_update_job').next_run_time) if scheduler.running and scheduler.get_job('price_update_job') else None
        }
    }

# Health check endpoint
@app.get("/health")
async def health_check():
    """Basic health check"""
    return {
        "status": "healthy",
        "scheduler_running": scheduler.running if 'scheduler' in globals() else False
    }

# Scheduler status endpoint
@app.get("/api/system/scheduler")
async def scheduler_status():
    """Get scheduler status and job information"""
    if not scheduler.running:
        return {"status": "disabled"}

    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time),
            "trigger": str(job.trigger)
        })

    return {
        "status": "running",
        "jobs": jobs
    }

if __name__ == "__main__":
    import uvicorn

    # Get configuration from environment
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "true").lower() == "true"

    logger.info(f"Starting server on {host}:{port}")

    # Run the application
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=reload
    )
