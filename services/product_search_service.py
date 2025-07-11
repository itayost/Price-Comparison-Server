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

        Args:
            query: Product name to search for
            city: City name to filter branches (will be standardized)
            limit: Maximum number of products to return

        Returns:
            List of products with their prices across all stores in the city
        """
        logger.info(f"Searching for '{query}' in {city}")

        # Standardize the input city name
        standardized_city = standardize_city_name(city)
        if city != standardized_city:
            logger.info(f"Standardized city: '{city}' -> '{standardized_city}'")

        # Normalize search query
        search_term = f"%{query}%"

        # First, find matching products
        matching_products = self.db.query(
            ChainProduct.barcode,
            ChainProduct.name,
            ChainProduct.chain_id,
            Chain.display_name.label('chain_name')
        ).join(
            Chain
        ).filter(
            ChainProduct.name.ilike(search_term)
        ).group_by(
            ChainProduct.barcode,
            ChainProduct.name,
            ChainProduct.chain_id,
            Chain.display_name
        ).limit(limit * 2).all()  # Get more to account for duplicates

        if not matching_products:
            logger.info(f"No products found matching '{query}'")
            return []

        # Group products by barcode
        products_by_barcode = {}
        for product in matching_products:
            if product.barcode not in products_by_barcode:
                products_by_barcode[product.barcode] = {
                    'barcode': product.barcode,
                    'name': product.name,
                    'chains': []
                }
            products_by_barcode[product.barcode]['chains'].append({
                'chain_id': product.chain_id,
                'chain_name': product.chain_name
            })

        # Get branches in the standardized city
        city_branches = self._get_branches_in_city(standardized_city)
        branch_ids = [branch.branch_id for branch in city_branches]

        if not branch_ids:
            logger.warning(f"No branches found in city: {standardized_city}")
            return []

        logger.info(f"Found {len(branch_ids)} branches in {standardized_city}")

        # Build result with prices
        results = []
        for barcode, product_info in list(products_by_barcode.items())[:limit]:
            product_result = {
                'barcode': barcode,
                'name': product_info['name'],
                'prices_by_store': []
            }

            # Get all prices for this product in the city
            prices = self.db.query(
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
                    ChainProduct.barcode == barcode,
                    Branch.branch_id.in_(branch_ids)
                )
            ).order_by(
                BranchPrice.price
            ).all()

            if prices:
                min_price = min(p.price for p in prices)
                max_price = max(p.price for p in prices)
                avg_price = sum(p.price for p in prices) / len(prices)

                for price_info in prices:
                    product_result['prices_by_store'].append({
                        'branch_id': price_info.branch_id,
                        'branch_name': price_info.branch_name,
                        'branch_address': price_info.address,
                        'chain_id': price_info.chain_id,
                        'chain_name': price_info.chain_name_key,
                        'chain_display_name': price_info.chain_display_name,
                        'price': float(price_info.price),
                        'is_cheapest': float(price_info.price) == min_price
                    })

                product_result['price_stats'] = {
                    'min_price': float(min_price),
                    'max_price': float(max_price),
                    'avg_price': float(avg_price),
                    'price_range': float(max_price - min_price),
                    'available_in_stores': len(prices)
                }
            else:
                product_result['price_stats'] = {
                    'min_price': 0,
                    'max_price': 0,
                    'avg_price': 0,
                    'price_range': 0,
                    'available_in_stores': 0
                }

            results.append(product_result)

        # Sort by availability
        results.sort(key=lambda x: x['price_stats']['available_in_stores'], reverse=True)

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
