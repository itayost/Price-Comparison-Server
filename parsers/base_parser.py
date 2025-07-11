# parsers/base_parser.py
"""
Updated base parser with city standardization
"""

from abc import ABC, abstractmethod
import logging
from typing import List, Dict, Any, Optional
import gzip
import requests
from datetime import datetime
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.city_utils import standardize_city_name

logger = logging.getLogger(__name__)


class BaseChainParser(ABC):
    """Base class for all chain parsers with city standardization"""

    def __init__(self, chain_name: str, chain_code: str):
        self.chain_name = chain_name
        self.chain_code = chain_code
        self.base_url = self.get_base_url()

    @abstractmethod
    def get_base_url(self) -> str:
        """Get the base URL for the chain's data files"""
        pass

    @abstractmethod
    def get_stores_file_url(self) -> str:
        """Get the URL for the stores list file"""
        pass

    @abstractmethod
    def get_price_files_list(self) -> List[str]:
        """Get list of price file URLs to download"""
        pass

    @abstractmethod
    def parse_stores_data(self, content: str) -> List[Dict[str, Any]]:
        """
        Parse stores data from XML content.

        Returns:
            List of dicts with: store_id, name, address, city
            Cities will be automatically standardized.
        """
        pass

    @abstractmethod
    def parse_price_data(self, content: str) -> List[Dict[str, Any]]:
        """
        Parse price data from XML content.

        Returns:
            List of dicts with: store_id, barcode, name, price
        """
        pass

    def download_file(self, url: str) -> Optional[str]:
        """Download and decompress a file"""
        try:
            logger.info(f"Downloading {url}")
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            # Decompress if gzipped
            if url.endswith('.gz'):
                content = gzip.decompress(response.content).decode('utf-8')
            else:
                content = response.text

            return content

        except Exception as e:
            logger.error(f"Error downloading {url}: {e}")
            return None

    def standardize_store_city(self, store_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Standardize the city name in store data.

        Args:
            store_data: Dict containing store information including 'city'

        Returns:
            Same dict with standardized city name
        """
        if 'city' in store_data:
            original_city = store_data['city']
            store_data['city'] = standardize_city_name(original_city)

            if original_city != store_data['city']:
                logger.debug(f"Standardized city for store {store_data.get('store_id', 'unknown')}: "
                           f"'{original_city}' -> '{store_data['city']}'")

        return store_data

    def get_stores(self) -> List[Dict[str, Any]]:
        """Download and parse stores data with standardized city names"""
        url = self.get_stores_file_url()
        content = self.download_file(url)

        if not content:
            return []

        stores = self.parse_stores_data(content)

        # Standardize city names for all stores
        standardized_stores = []
        for store in stores:
            standardized_stores.append(self.standardize_store_city(store))

        # Log city distribution after standardization
        city_counts = {}
        for store in standardized_stores:
            city = store.get('city', 'לא ידוע')
            city_counts[city] = city_counts.get(city, 0) + 1

        logger.info(f"Standardized {len(standardized_stores)} stores across {len(city_counts)} cities")
        logger.info(f"Top cities: {sorted(city_counts.items(), key=lambda x: x[1], reverse=True)[:5]}")

        return standardized_stores

    def get_prices(self, limit: Optional[int] = None) -> Dict[str, List[Dict[str, Any]]]:
        """Download and parse price data"""
        files = self.get_price_files_list()

        if limit:
            files = files[:limit]

        all_prices = {}

        for file_url in files:
            content = self.download_file(file_url)
            if content:
                prices = self.parse_price_data(content)
                if prices:
                    # Group by store_id
                    for price in prices:
                        store_id = price['store_id']
                        if store_id not in all_prices:
                            all_prices[store_id] = []
                        all_prices[store_id].append(price)

        return all_prices
