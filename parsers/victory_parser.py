# parsers/victory_parser.py
"""
Victory parser with city standardization
"""

import xml.etree.ElementTree as ET
from typing import List, Dict, Any
from .base_parser import BaseChainParser
import logging
import requests
from bs4 import BeautifulSoup
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.city_utils import standardize_city_name

logger = logging.getLogger(__name__)


class VictoryParser(BaseChainParser):
    """Parser for Victory chain data"""

    def __init__(self):
        super().__init__('victory', '7290696200003')
        self.base_url = 'https://laibcatalog.co.il'
        self.stores_list_url = 'https://laibcatalog.co.il/NBCompetitionRegulations.aspx?code=7290696200003&fileType=storesfull'
        self.prices_list_url = 'https://laibcatalog.co.il/NBCompetitionRegulations.aspx?code=7290696200003&fileType=pricefull'

    def get_base_url(self) -> str:
        """Get the base URL for Victory data files"""
        return self.base_url

    def get_stores_file_url(self) -> str:
        """Get the URL for the stores list file"""
        return self.stores_list_url

    def get_price_files_list(self) -> List[str]:
        """Get list of price file URLs to download"""
        return self.get_price_file_urls()

    def get_store_file_urls(self) -> List[str]:
        """Get Victory store file URLs - Fixed for case sensitivity and path issues"""
        try:
            response = requests.get(self.stores_list_url, timeout=30)
            if response.status_code != 200:
                logger.error(f"Failed to fetch {self.stores_list_url}: {response.status_code}")
                return []

            soup = BeautifulSoup(response.text, 'html.parser')

            # Find links with the download text
            links = soup.find_all('a', string='לחץ כאן להורדה')
            if not links:
                # Try with text parameter for older BeautifulSoup
                links = soup.find_all('a', text='לחץ כאן להורדה')

            file_urls = []
            for link in links:
                href = link.get('href')
                if href:
                    # Case-insensitive check for stores files
                    if 'stores' in href.lower() or 'storesfull' in href.lower():
                        # Fix mixed slashes
                        href = href.replace('\\', '/')

                        # Handle relative URLs
                        if not href.startswith('http'):
                            if href.startswith('/'):
                                href = self.base_url + href
                            else:
                                href = self.base_url + '/' + href

                        file_urls.append(href)
                        logger.info(f"Found Victory store file: {href}")

            return file_urls

        except Exception as e:
            logger.error(f"Error scraping Victory store files: {e}")
            return []

    def get_price_file_urls(self) -> List[str]:
        """Get Victory price file URLs"""
        try:
            response = requests.get(self.prices_list_url, timeout=30)
            if response.status_code != 200:
                logger.error(f"Failed to fetch {self.prices_list_url}: {response.status_code}")
                return []

            soup = BeautifulSoup(response.text, 'html.parser')

            # Find download links
            links = soup.find_all('a', string='לחץ כאן להורדה')
            if not links:
                links = soup.find_all('a', text='לחץ כאן להורדה')

            file_urls = []
            for link in links:
                href = link.get('href')
                if href:
                    # Check for price files
                    if 'price' in href.lower():
                        # Fix mixed slashes
                        href = href.replace('\\', '/')

                        # Handle relative URLs
                        if not href.startswith('http'):
                            if href.startswith('/'):
                                href = self.base_url + href
                            else:
                                href = self.base_url + '/' + href

                        file_urls.append(href)

            logger.info(f"Found {len(file_urls)} Victory price files")
            return file_urls

        except Exception as e:
            logger.error(f"Error scraping Victory price files: {e}")
            return []

    def parse_stores_data(self, content: str) -> List[Dict[str, Any]]:
        """Parse stores data from XML content with city standardization"""
        stores = []

        try:
            root = ET.fromstring(content)

            # Victory structure: /Store/Branches/Branch
            branches = root.find('.//Branches')
            if branches is None:
                logger.error("No Branches element found in Victory XML")
                return stores

            store_elements = branches.findall('Branch')
            logger.info(f"Found {len(store_elements)} store elements in Victory XML")

            for store in store_elements:
                try:
                    # Extract store data - Victory uses mixed case
                    store_id_elem = store.find('StoreID')
                    if store_id_elem is None or not store_id_elem.text:
                        continue

                    # Get city and standardize it
                    city_elem = store.find('City')
                    city_raw = city_elem.text.strip() if city_elem is not None and city_elem.text else "Unknown"
                    city_standardized = standardize_city_name(city_raw)

                    if city_raw != city_standardized:
                        logger.debug(f"Standardized city for store {store_id_elem.text}: '{city_raw}' -> '{city_standardized}'")

                    store_data = {
                        'store_id': store_id_elem.text.strip(),
                        'name': store.find('StoreName').text if store.find('StoreName') is not None else f"Store {store_id_elem.text}",
                        'address': store.find('Address').text if store.find('Address') is not None else "Unknown",
                        'city': city_standardized,  # Use standardized city name
                    }

                    stores.append(store_data)
                    logger.debug(f"Parsed Victory store: {store_data['store_id']} - {store_data['name']} - {store_data['city']}")

                except Exception as e:
                    logger.warning(f"Error parsing Victory store element: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error parsing Victory store XML: {e}")

        logger.info(f"Successfully parsed {len(stores)} Victory stores")
        return stores

    def parse_price_data(self, content: str) -> List[Dict[str, Any]]:
        """Parse price data from XML content"""
        prices = []

        try:
            root = ET.fromstring(content)

            # Get store info from root
            store_id = None
            for field in ['StoreID', 'StoreId', 'STOREID']:
                elem = root.find(f'.//{field}')
                if elem is not None and elem.text:
                    store_id = elem.text.strip()
                    break

            if not store_id:
                logger.warning("No store ID found in Victory price file")
                return prices

            # Find products
            products = root.findall('.//Product')
            if not products:
                products = root.findall('.//Item')

            logger.info(f"Found {len(products)} products in Victory price file for store {store_id}")

            for product in products:
                try:
                    # Get barcode
                    barcode = None
                    for field in ['ItemCode', 'Barcode', 'ItemBarcode']:
                        elem = product.find(field)
                        if elem is not None and elem.text:
                            barcode = elem.text.strip()
                            break

                    if not barcode:
                        continue

                    # Get price
                    price = None
                    for field in ['ItemPrice', 'Price', 'UnitPrice']:
                        elem = product.find(field)
                        if elem is not None and elem.text:
                            try:
                                price = float(elem.text.strip())
                                break
                            except ValueError:
                                continue

                    if price is None:
                        continue

                    # Get name
                    name = None
                    for field in ['ItemName', 'Name', 'ItemDescription']:
                        elem = product.find(field)
                        if elem is not None and elem.text:
                            name = elem.text.strip()
                            break

                    if not name:
                        name = f"Product {barcode}"

                    prices.append({
                        'store_id': store_id,
                        'barcode': barcode,
                        'name': name,
                        'price': price
                    })

                except Exception as e:
                    logger.warning(f"Error parsing Victory product: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error parsing Victory price XML: {e}")

        logger.info(f"Successfully parsed {len(prices)} prices")
        return prices
