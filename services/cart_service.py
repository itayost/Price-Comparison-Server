# services/cart_service.py
"""
Cart comparison service with standardized city names
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import logging
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.new_models import Chain, Branch, ChainProduct, BranchPrice
from utils.city_utils import standardize_city_name

logger = logging.getLogger(__name__)


@dataclass
class CartItem:
    """Item in shopping cart"""
    barcode: str
    quantity: int = 1
    name: Optional[str] = None


@dataclass
class StorePrice:
    """Price information for a store"""
    branch_id: int
    branch_name: str
    branch_address: str
    city: str
    chain_name: str
    chain_display_name: str
    available_items: int
    missing_items: int
    total_price: float
    items_detail: List[Dict[str, Any]]


@dataclass
class CartComparison:
    """Complete cart comparison result"""
    cart_items: List[CartItem]
    total_items: int
    cheapest_store: Optional[StorePrice]
    all_stores: List[StorePrice]
    comparison_time: datetime
    city: str


class CartComparisonService:
    """Service for comparing cart prices across stores"""

    def __init__(self, db: Session):
        self.db = db

    def compare_cart(self, items: List[CartItem], city: str) -> CartComparison:
        """
        Find the cheapest store for a shopping cart.

        Args:
            items: List of items with barcode and quantity
            city: City name to search in (will be standardized)

        Returns:
            CartComparison with cheapest store and all store comparisons
        """
        logger.info(f"Comparing cart with {len(items)} items in {city}")

        # Standardize city name
        standardized_city = standardize_city_name(city)
        if city != standardized_city:
            logger.info(f"Standardized city: '{city}' -> '{standardized_city}'")

        # Get all branches in the city
        branches = self._get_branches_in_city(standardized_city)
        if not branches:
            logger.warning(f"No stores found in city: {standardized_city}")
            return CartComparison(
                cart_items=items,
                total_items=len(items),
                cheapest_store=None,
                all_stores=[],
                comparison_time=datetime.utcnow(),
                city=standardized_city
            )

        logger.info(f"Found {len(branches)} stores in {standardized_city}")

        # Calculate prices for each store
        store_prices = []
        for branch in branches:
            store_price = self._calculate_store_price(branch, items)
            if store_price.available_items > 0:  # Only include stores with at least one item
                store_prices.append(store_price)

        # Sort by total price (cheapest first)
        store_prices.sort(key=lambda x: x.total_price)

        # Find cheapest store with most items
        cheapest = self._find_best_store(store_prices)

        return CartComparison(
            cart_items=items,
            total_items=len(items),
            cheapest_store=cheapest,
            all_stores=store_prices,
            comparison_time=datetime.utcnow(),
            city=standardized_city
        )

    def _get_branches_in_city(self, city: str) -> List[Branch]:
        """
        Get all branches in a city.
        Since cities are now standardized, we can use exact match.
        """
        # Use exact match since cities are standardized
        branches = self.db.query(Branch).filter(
            Branch.city == city
        ).all()

        if branches:
            logger.debug(f"Found {len(branches)} branches in {city}")
        else:
            # Log available cities for debugging
            sample_cities = self.db.query(Branch.city).distinct().limit(5).all()
            logger.debug(f"No branches in '{city}'. Sample cities: {[c[0] for c in sample_cities]}")

        return branches

    def _calculate_store_price(self, branch: Branch, items: List[CartItem]) -> StorePrice:
        """Calculate total price for cart at a specific store"""
        total_price = 0.0
        available_items = 0
        missing_items = 0
        items_detail = []

        for item in items:
            # Find product price at this branch
            price_info = self.db.query(
                BranchPrice.price,
                ChainProduct.name
            ).join(
                ChainProduct
            ).filter(
                and_(
                    ChainProduct.barcode == item.barcode,
                    ChainProduct.chain_id == branch.chain_id,
                    BranchPrice.branch_id == branch.branch_id
                )
            ).first()

            if price_info:
                price, product_name = price_info
                # Convert Decimal to float
                price_float = float(price)
                item_total = price_float * item.quantity
                total_price += item_total
                available_items += 1

                items_detail.append({
                    'barcode': item.barcode,
                    'name': product_name or item.name or f'Product {item.barcode}',
                    'quantity': item.quantity,
                    'unit_price': price_float,
                    'total_price': item_total,
                    'available': True
                })
            else:
                missing_items += 1
                items_detail.append({
                    'barcode': item.barcode,
                    'name': item.name or f'Product {item.barcode}',
                    'quantity': item.quantity,
                    'unit_price': 0,
                    'total_price': 0,
                    'available': False
                })

        # Get chain info
        chain = self.db.query(Chain).filter(Chain.chain_id == branch.chain_id).first()

        return StorePrice(
            branch_id=branch.branch_id,
            branch_name=branch.name,
            branch_address=branch.address,
            city=branch.city,
            chain_name=chain.name if chain else 'unknown',
            chain_display_name=chain.display_name if chain else 'Unknown',
            available_items=available_items,
            missing_items=missing_items,
            total_price=total_price,
            items_detail=items_detail
        )

    def _find_best_store(self, store_prices: List[StorePrice]) -> Optional[StorePrice]:
        """
        Find the best store considering both price and item availability.

        Strategy:
        1. Prefer stores with all items
        2. Among stores with same availability, choose cheapest
        3. If no store has all items, choose the one with most items and good price
        """
        if not store_prices:
            return None

        # Group by number of available items
        by_availability = {}
        for store in store_prices:
            count = store.available_items
            if count not in by_availability:
                by_availability[count] = []
            by_availability[count].append(store)

        # Get the highest availability count
        max_items = max(by_availability.keys())

        # Return cheapest among stores with most items
        best_stores = by_availability[max_items]
        return min(best_stores, key=lambda x: x.total_price)

    def get_product_info(self, barcode: str) -> Optional[Dict[str, Any]]:
        """Get product information across all chains"""
        products = self.db.query(
            ChainProduct.name,
            ChainProduct.chain_id,
            Chain.display_name
        ).join(
            Chain
        ).filter(
            ChainProduct.barcode == barcode
        ).all()

        if not products:
            return None

        # Return the first product found (they should all be the same product)
        name, chain_id, chain_name = products[0]

        # Get price range
        prices = self.db.query(
            func.min(BranchPrice.price).label('min_price'),
            func.max(BranchPrice.price).label('max_price'),
            func.avg(BranchPrice.price).label('avg_price')
        ).join(
            ChainProduct
        ).filter(
            ChainProduct.barcode == barcode
        ).first()

        return {
            'barcode': barcode,
            'name': name,
            'found_in_chains': len(products),
            'price_range': {
                'min': float(prices.min_price) if prices.min_price else 0,
                'max': float(prices.max_price) if prices.max_price else 0,
                'avg': float(prices.avg_price) if prices.avg_price else 0
            }
        }

    def search_products(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search for products by name or barcode"""
        # Search in product names
        products = self.db.query(
            ChainProduct.barcode,
            ChainProduct.name,
            func.count(BranchPrice.price_id).label('availability')
        ).outerjoin(
            BranchPrice
        ).filter(
            ChainProduct.name.ilike(f'%{query}%')
        ).group_by(
            ChainProduct.barcode,
            ChainProduct.name
        ).limit(limit).all()

        results = []
        for barcode, name, availability in products:
            results.append({
                'barcode': barcode,
                'name': name,
                'availability': availability
            })

        return results
