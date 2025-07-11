# price_comparison_server/services/product_search_service.py

from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
import logging

from database.new_models import Chain, Branch, ChainProduct, BranchPrice

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
            city: City name to filter branches
            limit: Maximum number of products to return
            
        Returns:
            List of products with their prices across all stores in the city
        """
        logger.info(f"Searching for '{query}' in {city}")
        
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

        # Group products by barcode to handle same product in different chains
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

        # Get branches in the city with flexible matching
        city_branches = self._get_branches_in_city(city)
        branch_ids = [branch.branch_id for branch in city_branches]

        if not branch_ids:
            logger.warning(f"No branches found in city: {city}")
            # Return products without prices
            return []

        logger.info(f"Found {len(branch_ids)} branches in {city}")

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
                Chain.chain_id,
                Chain.name.label('chain_name_key'),
                Chain.display_name.label('chain_display_name'),
                ChainProduct.chain_product_id
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

            # Add price information
            for price_info in prices:
                product_result['prices_by_store'].append({
                    'branch_id': price_info.branch_id,
                    'branch_name': price_info.branch_name,
                    'branch_address': price_info.address,
                    'chain_id': price_info.chain_id,
                    'chain_name': price_info.chain_name_key,
                    'chain_display_name': price_info.chain_display_name,
                    'price': float(price_info.price)
                })

            # Calculate price statistics
            if product_result['prices_by_store']:
                prices_list = [p['price'] for p in product_result['prices_by_store']]
                product_result['price_stats'] = {
                    'min_price': min(prices_list),
                    'max_price': max(prices_list),
                    'avg_price': sum(prices_list) / len(prices_list),
                    'price_range': max(prices_list) - min(prices_list),
                    'available_in_stores': len(prices_list)
                }

                # Mark cheapest store
                min_price = product_result['price_stats']['min_price']
                for store in product_result['prices_by_store']:
                    store['is_cheapest'] = store['price'] == min_price
            else:
                product_result['price_stats'] = {
                    'min_price': 0,
                    'max_price': 0,
                    'avg_price': 0,
                    'price_range': 0,
                    'available_in_stores': 0
                }

            results.append(product_result)

        # Sort by availability (products available in more stores first)
        results.sort(key=lambda x: x['price_stats']['available_in_stores'], reverse=True)

        return results

    def get_product_details_by_barcode(self, barcode: str, city: str) -> Optional[Dict[str, Any]]:
        """Get detailed price information for a specific product in a city"""

        city_branches = self._get_branches_in_city(city)
        branch_ids = [branch.branch_id for branch in city_branches]

        if not branch_ids:
            logger.warning(f"No branches found in city: {city}")
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
                'city': city,
                'available': False,
                'message': f'Product not available in {city}'
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
            'city': city,
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

    def _normalize_city(self, city: str) -> List[str]:
        """Normalize city name for better matching - handles Tel Aviv variations"""
        # Remove extra spaces and strip
        city = ' '.join(city.split()).strip()

        # Handle Tel Aviv variations specifically
        city_mappings = {
            'תל אביב': ['תל אביב', 'תל-אביב', 'תל אבית יפה'],
            'tel aviv': ['תל אביב', 'תל-אביב'],
            'תל אביב יפו': ['תל אביב', 'תל-אביב'],
            'ירושלים': ['ירושלים'],
            'jerusalem': ['ירושלים'],
            'חיפה': ['חיפה'],
            'haifa': ['חיפה'],
        }

        # Check if input matches any mapping key
        city_lower = city.lower()
        for key, variations in city_mappings.items():
            if city_lower == key.lower():
                return variations  # Return list of variations to search for

        return [city]  # Return as list for consistent handling

    def _get_branches_in_city(self, city: str) -> List[Branch]:
        """Get all branches in a city with very flexible matching"""
        # Get normalized city variations
        city_variations = self._normalize_city(city)

        if not isinstance(city_variations, list):
            city_variations = [city_variations]

        all_branches = []

        for city_variant in city_variations:
            # Try exact match first
            branches = self.db.query(Branch).filter(
                Branch.city == city_variant
            ).all()

            # If no exact match, try case-insensitive partial match
            if not branches:
                branches = self.db.query(Branch).filter(
                    func.lower(Branch.city).like(f'%{city_variant.lower()}%')
                ).all()

            all_branches.extend(branches)

        # Remove duplicates by branch_id
        unique_branches = []
        seen_ids = set()
        for branch in all_branches:
            if branch.branch_id not in seen_ids:
                unique_branches.append(branch)
                seen_ids.add(branch.branch_id)

        # Log what we found
        if unique_branches:
            logger.info(f"Found {len(unique_branches)} branches for city '{city}' (searching variations: {city_variations})")
            # Group by chain for debugging
            by_chain = {}
            for branch in unique_branches:
                try:
                    chain_name = branch.chain.display_name if hasattr(branch, 'chain') else 'Unknown'
                except:
                    chain_name = 'Unknown'
                if chain_name not in by_chain:
                    by_chain[chain_name] = 0
                by_chain[chain_name] += 1
            logger.info(f"  Branch distribution: {by_chain}")
        else:
            logger.warning(f"No branches found for city '{city}' with variations {city_variations}")
            # Log available cities for debugging
            sample_cities = self.db.query(Branch.city).distinct().limit(10).all()
            logger.debug(f"Available cities (sample): {[c[0] for c in sample_cities]}")

        return unique_branches
