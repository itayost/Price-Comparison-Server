# services/product_search_service.py
"""
Simplified product search service with standardized city names
"""

from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
import logging
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.new_models import Chain, Branch, ChainProduct, BranchPrice
from utils.city_utils import standardize_city_name, get_city_variations

logger = logging.getLogger(__name__)


class ProductSearchService:
    """Service for searching products with price details by city"""

    def __init__(self, db: Session):
        self.db = db

    def search_products_with_prices(self, query: str, city: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Search for products and return all prices in the specified city.
        Only returns products that have at least one price in the city.
        """
        logger.info(f"Searching for '{query}' in {city}")

        # Standardize the input city name
        standardized_city = standardize_city_name(city)
        if city != standardized_city:
            logger.info(f"Standardized city: '{city}' -> '{standardized_city}'")

        # Normalize search query
        search_term = f"%{query}%"

        # Get branches in the standardized city
        city_branches = self._get_branches_in_city(standardized_city)
        branch_ids = [branch.branch_id for branch in city_branches]

        if not branch_ids:
            logger.warning(f"No branches found in city: {standardized_city}")
            return []

        logger.info(f"Found {len(branch_ids)} branches in {standardized_city}")

        # NEW APPROACH: Search for products that have prices in this city
        # This query joins all tables to ensure we only get products with prices
        products_with_prices = self.db.query(
            ChainProduct.barcode,
            ChainProduct.name,
            func.count(BranchPrice.price_id).label('price_count'),
            func.min(BranchPrice.price).label('min_price'),
            func.max(BranchPrice.price).label('max_price'),
            func.avg(BranchPrice.price).label('avg_price')
        ).join(
            BranchPrice,
            ChainProduct.chain_product_id == BranchPrice.chain_product_id
        ).join(
            Branch,
            BranchPrice.branch_id == Branch.branch_id
        ).filter(
            and_(
                ChainProduct.name.ilike(search_term),
                Branch.branch_id.in_(branch_ids)
            )
        ).group_by(
            ChainProduct.barcode,
            ChainProduct.name
        ).order_by(
            func.count(BranchPrice.price_id).desc()  # Products with most availability first
        ).limit(limit).all()

        if not products_with_prices:
            logger.info(f"No products with prices found matching '{query}' in {standardized_city}")
            return []

        # Build detailed results
        results = []
        for product in products_with_prices:
            product_result = {
                'barcode': product.barcode,
                'name': product.name,
                'prices_by_store': [],
                'price_stats': {
                    'min_price': float(product.min_price),
                    'max_price': float(product.max_price),
                    'avg_price': float(product.avg_price),
                    'price_range': float(product.max_price - product.min_price),
                    'available_in_stores': product.price_count
                }
            }

            # Get detailed price information for each store
            detailed_prices = self.db.query(
                BranchPrice.price,
                Branch.branch_id,
                Branch.name.label('branch_name'),
                Branch.address,
                Branch.chain_id,
                Chain.name.label('chain_name_key'),
                Chain.display_name.label('chain_display_name')
            ).join(
                ChainProduct,
                BranchPrice.chain_product_id == ChainProduct.chain_product_id
            ).join(
                Branch,
                BranchPrice.branch_id == Branch.branch_id
            ).join(
                Chain,
                Branch.chain_id == Chain.chain_id
            ).filter(
                and_(
                    ChainProduct.barcode == product.barcode,
                    Branch.branch_id.in_(branch_ids)
                )
            ).order_by(
                BranchPrice.price
            ).all()

            for price_info in detailed_prices:
                product_result['prices_by_store'].append({
                    'branch_id': price_info.branch_id,
                    'branch_name': price_info.branch_name,
                    'branch_address': price_info.address,
                    'chain_id': price_info.chain_id,
                    'chain_name': price_info.chain_name_key,
                    'chain_display_name': price_info.chain_display_name,
                    'price': float(price_info.price),
                    'is_cheapest': float(price_info.price) == float(product.min_price)
                })

            results.append(product_result)

        logger.info(f"Returning {len(results)} products with prices")
        return results

    def get_product_details_by_barcode(self, barcode: str, city: str) -> Optional[Dict[str, Any]]:
        """Get detailed price information for a specific product in a city"""

        # Standardize city name
        standardized_city = standardize_city_name(city)

        city_branches = self._get_branches_in_city(standardized_city)
        branch_ids = [branch.branch_id for branch in city_branches]

        if not branch_ids:
            logger.warning(f"No branches found in city: {standardized_city}")
            return None

        # Get product info
        product = self.db.query(ChainProduct).filter(
            ChainProduct.barcode == barcode
        ).first()

        if not product:
            logger.warning(f"Product with barcode {barcode} not found")
            return None

        # Get all prices in the city
        prices = self.db.query(
            BranchPrice.price,
            Branch.branch_id,
            Branch.name.label('branch_name'),
            Branch.address,
            Branch.city,
            Chain.chain_id,
            Chain.name.label('chain_name_key'),
            Chain.display_name.label('chain_display_name')
        ).join(
            ChainProduct,
            BranchPrice.chain_product_id == ChainProduct.chain_product_id
        ).join(
            Branch,
            BranchPrice.branch_id == Branch.branch_id
        ).join(
            Chain,
            Branch.chain_id == Chain.chain_id
        ).filter(
            and_(
                ChainProduct.barcode == barcode,
                Branch.branch_id.in_(branch_ids)
            )
        ).order_by(
            BranchPrice.price
        ).all()

        if not prices:
            return {
                'barcode': barcode,
                'name': product.name,
                'city': standardized_city,
                'available': False,
                'message': f'Product not available in {standardized_city}'
            }

        # Build detailed response
        prices_by_chain = {}
        all_prices = []

        for price_info in prices:
            chain_name = price_info.chain_display_name
            if chain_name not in prices_by_chain:
                prices_by_chain[chain_name] = []

            store_price = {
                'branch_id': price_info.branch_id,
                'branch_name': price_info.branch_name,
                'branch_address': price_info.address,
                'price': float(price_info.price)
            }

            prices_by_chain[chain_name].append(store_price)
            all_prices.append(float(price_info.price))

        return {
            'barcode': barcode,
            'name': product.name,
            'city': standardized_city,
            'available': True,
            'price_summary': {
                'min_price': min(all_prices),
                'max_price': max(all_prices),
                'avg_price': sum(all_prices) / len(all_prices),
                'savings_potential': max(all_prices) - min(all_prices),
                'total_stores': len(all_prices)
            },
            'prices_by_chain': prices_by_chain,
            'all_prices': [
                {
                    'branch_name': p.branch_name,
                    'chain': p.chain_display_name,
                    'address': p.address,
                    'price': float(p.price),
                    'is_cheapest': float(p.price) == min(all_prices)
                }
                for p in prices
            ]
        }

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
