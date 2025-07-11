# price_comparison_server/routes/product_routes.py

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
import logging

from database.connection import SessionLocal
from services.product_search_service import ProductSearchService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/products", tags=["products"])


# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/search", response_model=List[Dict[str, Any]])
async def search_products(
    query: str = Query(..., description="Product name to search for"),
    city: str = Query(..., description="City name to filter branches"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of products to return"),
    db: Session = Depends(get_db)
):
    """
    Search for products and return all prices in the specified city.
    
    This endpoint searches for products by name and returns detailed price information
    for all stores in the specified city, including price statistics and the cheapest store.
    
    Args:
        query: Product name to search for (partial matching supported)
        city: City name to filter branches (Hebrew or English)
        limit: Maximum number of products to return (1-100, default: 20)
        
    Returns:
        List of products with:
        - barcode: Product barcode
        - name: Product name in Hebrew
        - prices_by_store: List of prices at different stores
        - price_stats: Statistics including min, max, avg prices
    """
    try:
        search_service = ProductSearchService(db)
        results = search_service.search_products_with_prices(query, city, limit)
        
        if not results:
            logger.info(f"No products found for query '{query}' in {city}")
            return []
        
        logger.info(f"Found {len(results)} products for query '{query}' in {city}")
        return results
        
    except Exception as e:
        logger.error(f"Error searching products: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to search products")


@router.get("/barcode/{barcode}", response_model=Optional[Dict[str, Any]])
async def get_product_by_barcode(
    barcode: str,
    city: str = Query(..., description="City name to filter branches"),
    db: Session = Depends(get_db)
):
    """
    Get detailed price information for a specific product in a city.
    
    This endpoint retrieves comprehensive price information for a single product
    identified by its barcode, showing all available prices in the specified city.
    
    Args:
        barcode: Product barcode
        city: City name to filter branches
        
    Returns:
        Detailed product information including:
        - Product details (barcode, name)
        - Price summary (min, max, avg, savings potential)
        - Prices by chain (grouped by supermarket chain)
        - All individual store prices sorted by price
    """
    try:
        search_service = ProductSearchService(db)
        result = search_service.get_product_details_by_barcode(barcode, city)
        
        if not result:
            raise HTTPException(
                status_code=404, 
                detail=f"Product with barcode {barcode} not found"
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting product details: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get product details")


@router.get("/cities", response_model=List[str])
async def get_available_cities(db: Session = Depends(get_db)):
    """
    Get list of all cities with available branches.
    
    Returns:
        List of unique city names where stores are available
    """
    try:
        from database.new_models import Branch
        
        # Get unique cities
        cities = db.query(Branch.city).distinct().order_by(Branch.city).all()
        city_list = [city[0] for city in cities if city[0]]
        
        return city_list
        
    except Exception as e:
        logger.error(f"Error getting cities: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get cities")


@router.get("/chains", response_model=List[Dict[str, Any]])
async def get_available_chains(db: Session = Depends(get_db)):
    """
    Get list of all available supermarket chains.
    
    Returns:
        List of chains with their IDs and display names
    """
    try:
        from database.new_models import Chain
        
        chains = db.query(Chain).all()
        return [
            {
                "chain_id": chain.chain_id,
                "name": chain.name,
                "display_name": chain.display_name
            }
            for chain in chains
        ]
        
    except Exception as e:
        logger.error(f"Error getting chains: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get chains")


@router.get("/branches/{city}", response_model=List[Dict[str, Any]])
async def get_branches_in_city(
    city: str,
    chain_id: Optional[int] = Query(None, description="Filter by chain ID"),
    db: Session = Depends(get_db)
):
    """
    Get all branches in a specific city.
    
    Args:
        city: City name
        chain_id: Optional chain ID to filter by specific chain
        
    Returns:
        List of branches with details
    """
    try:
        from database.new_models import Branch, Chain
        from sqlalchemy import func

        # Normalize city name
        search_service = ProductSearchService(db)
        city_normalized = search_service._normalize_city(city)

        # Build query
        query = db.query(
            Branch.branch_id,
            Branch.name,
            Branch.address,
            Branch.city,
            Chain.chain_id,
            Chain.display_name.label('chain_name')
        ).join(Chain)

        # Apply filters
        query = query.filter(
            func.lower(Branch.city).like(f'%{city_normalized.lower()}%')
        )

        if chain_id:
            query = query.filter(Chain.chain_id == chain_id)

        branches = query.order_by(Chain.display_name, Branch.name).all()

        return [
            {
                "branch_id": branch.branch_id,
                "name": branch.name,
                "address": branch.address,
                "city": branch.city,
                "chain_id": branch.chain_id,
                "chain_name": branch.chain_name
            }
            for branch in branches
        ]

    except Exception as e:
        logger.error(f"Error getting branches: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get branches")


@router.get("/autocomplete", response_model=List[str])
async def autocomplete_products(
    query: str = Query(..., min_length=2, description="Partial product name"),
    limit: int = Query(10, ge=1, le=50, description="Maximum suggestions"),
    db: Session = Depends(get_db)
):
    """
    Get product name suggestions for autocomplete.
    
    Args:
        query: Partial product name (minimum 2 characters)
        limit: Maximum number of suggestions (1-50, default: 10)
        
    Returns:
        List of product names matching the query
    """
    try:
        from database.new_models import ChainProduct
        from sqlalchemy import func
        
        # Search for matching product names
        search_term = f"%{query}%"
        
        suggestions = db.query(
            ChainProduct.name
        ).filter(
            ChainProduct.name.ilike(search_term)
        ).distinct().limit(limit).all()
        
        return [name[0] for name in suggestions]
        
    except Exception as e:
        logger.error(f"Error getting autocomplete suggestions: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get suggestions")


# Example response models for documentation
example_search_response = [
    {
        "barcode": "7290000000001",
        "name": "חלב טרי 3% 1 ליטר",
        "prices_by_store": [
            {
                "branch_id": 1,
                "branch_name": "שופרסל ביג תל אביב",
                "branch_address": "רח' דיזנגוף 50",
                "chain_id": 1,
                "chain_name": "shufersal",
                "chain_display_name": "שופרסל",
                "price": 5.90,
                "is_cheapest": True
            },
            {
                "branch_id": 2,
                "branch_name": "ויקטורי רמת אביב",
                "branch_address": "רח' איינשטיין 40",
                "chain_id": 2,
                "chain_name": "victory",
                "chain_display_name": "ויקטורי",
                "price": 6.50,
                "is_cheapest": False
            }
        ],
        "price_stats": {
            "min_price": 5.90,
            "max_price": 6.50,
            "avg_price": 6.20,
            "price_range": 0.60,
            "available_in_stores": 2
        }
    }
]

example_barcode_response = {
    "barcode": "7290000000001",
    "name": "חלב טרי 3% 1 ליטר",
    "city": "תל אביב",
    "available": True,
    "price_summary": {
        "min_price": 5.90,
        "max_price": 6.50,
        "avg_price": 6.20,
        "savings_potential": 0.60,
        "total_stores": 2
    },
    "prices_by_chain": {
        "שופרסל": [
            {
                "branch_id": 1,
                "branch_name": "שופרסל ביג תל אביב",
                "branch_address": "רח' דיזנגוף 50",
                "price": 5.90
            }
        ],
        "ויקטורי": [
            {
                "branch_id": 2,
                "branch_name": "ויקטורי רמת אביב",
                "branch_address": "רח' איינשטיין 40",
                "price": 6.50
            }
        ]
    },
    "all_prices": [
        {
            "branch_name": "שופרסל ביג תל אביב",
            "chain": "שופרסל",
            "address": "רח' דיזנגוף 50",
            "price": 5.90,
            "is_cheapest": True
        },
        {
            "branch_name": "ויקטורי רמת אביב",
            "chain": "ויקטורי",
            "address": "רח' איינשטיין 40",
            "price": 6.50,
            "is_cheapest": False
        }
    ]
}
