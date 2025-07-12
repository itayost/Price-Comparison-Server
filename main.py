# main.py
"""Main FastAPI application with automatic database setup"""
import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

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
            # You might want to exit here
        elif not health['has_data']:
            logger.warning("⚠️  Server starting without price data!")
            logger.warning("   API will work but price comparisons will return no results")
            logger.warning("   Run import scripts or set AUTO_IMPORT=true in .env")
        else:
            logger.info(f"✅ Database ready with {health['products']} products and {health['prices']} prices")

    except Exception as e:
        logger.error(f"❌ Startup failed: {e}")
        # Decide if you want to fail or continue
        # raise  # Uncomment to prevent server start on DB issues

    yield

    # Shutdown
    logger.info("👋 Shutting down Price Comparison Server...")

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
        "health": "/api/system/health"
    }

# Health check endpoint
@app.get("/health")
async def health_check():
    """Basic health check"""
    return {"status": "healthy"}

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
