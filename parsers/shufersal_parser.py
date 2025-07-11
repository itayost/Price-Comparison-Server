# parsers/shufersal_parser.py
"""
Shufersal parser with city standardization
"""

import xml.etree.ElementTree as ET
from typing import List, Dict, Any
from .base_parser import BaseChainParser
import logging
import requests
from bs4 import BeautifulSoup
import re
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.city_utils import standardize_city_name

logger = logging.getLogger(__name__)


class ShufersalParser(BaseChainParser):
    """Parser for Shufersal chain data with pagination support"""

    def __init__(self):
        super().__init__('shufersal', '7290027600007')
        self.stores_list_url = 'https://prices.shufersal.co.il/FileObject/UpdateCategory?catID=5'
        self.prices_list_url = 'https://prices.shufersal.co.il/FileObject/UpdateCategory?catID=2&storeId=0&page='

    def get_base_url(self) -> str:
        """Get the base URL for Shufersal data files"""
        return 'https://prices.shufersal.co.il'

    def get_stores_file_url(self) -> str:
        """Get the URL for the stores list file"""
        return self.stores_list_url

    def get_price_files_list(self) -> List[str]:
        """Get list of price file URLs to download"""
        return self.get_price_file_urls()

    def get_store_file_urls(self) -> List[str]:
        """Get Shufersal store file URLs"""
        return self.scrape_file_list(
            self.stores_list_url,
            {'tag': 'a', 'text': 'לחץ להורדה'},
            'Stores'
        )

    def get_price_file_urls(self) -> List[str]:
        """Get Shufersal price file URLs with pagination"""
        logger.info("Getting Shufersal price file URLs...")

        # First, find the last page number
        last_page = self._get_last_page_number()
        logger.info(f"Found {last_page} pages of price files")

        all_urls = []
        seen_files = set()

        # Process all pages
        for page in range(1, last_page + 1):
            logger.info(f"Processing page {page}/{last_page}")
            page_url = f"{self.prices_list_url}{page}"

            try:
                response = requests.get(page_url, timeout=30)
                if response.status_code != 200:
                    logger.error(f"Failed to fetch page {page}: {response.status_code}")
                    continue

                soup = BeautifulSoup(response.text, 'html.parser')

                # Find all download links - they're in anchor tags with specific text
                links = soup.find_all('a', string='לחץ להורדה')
                if not links:
                    # Try alternative method
                    links = []
                    for a in soup.find_all('a'):
                        if a.get_text(strip=True) == 'לחץ להורדה':
                            links.append(a)

                logger.info(f"Found {len(links)} download links on page {page}")

                page_files = 0
                for link in links:
                    href = link.get('href')
                    if href and 'price' in href.lower():
                        # Extract filename for deduplication
                        filename = href.split('/')[-1].split('?')[0]

                        if filename not in seen_files:
                            seen_files.add(filename)
                            all_urls.append(href)
                            page_files += 1

                logger.info(f"Added {page_files} new price files from page {page}")

            except Exception as e:
                logger.error(f"Error processing page {page}: {e}")
                continue

        logger.info(f"Found {len(all_urls)} unique price files")
        return all_urls

    def _get_last_page_number(self) -> int:
        """Find the last page number from the >> button"""
        try:
            # Check first page
            response = requests.get(f"{self.prices_list_url}1", timeout=30)
            if response.status_code != 200:
                return 1

            soup = BeautifulSoup(response.text, 'html.parser')

            # Find >> link
            for link in soup.find_all('a'):
                if link.get_text(strip=True) == '>>':
                    href = link.get('href', '')
                    match = re.search(r'page=(\d+)', href)
                    if match:
                        return int(match.group(1))

            logger.warning("Could not find >> button, defaulting to 1 page")
            return 1

        except Exception as e:
            logger.error(f"Error finding last page: {e}")
            return 1

    def parse_stores_data(self, content: str) -> List[Dict[str, Any]]:
        """Parse stores data from XML content with city standardization"""
        stores = []

        try:
            root = ET.fromstring(content)

            # Find all stores
            store_elements = root.findall('.//STORE')
            logger.info(f"Found {len(store_elements)} stores in file")

            for store in store_elements:
                try:
                    # Get store ID and remove leading zeros
                    store_id_elem = store.find('STOREID')
                    if store_id_elem is None or not store_id_elem.text:
                        continue

                    store_id = str(int(store_id_elem.text.strip()))

                    # Get city and standardize it
                    city_raw = self._get_text(store, 'CITY', '')
                    city_standardized = standardize_city_name(city_raw)

                    if city_raw != city_standardized:
                        logger.debug(f"Standardized city for store {store_id}: '{city_raw}' -> '{city_standardized}'")

                    store_data = {
                        'store_id': store_id,
                        'name': self._get_text(store, 'STORENAME', f"Store {store_id}"),
                        'address': self._get_text(store, 'ADDRESS', ''),
                        'city': city_standardized,  # Use standardized city name
                    }

                    stores.append(store_data)

                except Exception as e:
                    logger.warning(f"Error parsing store element: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error parsing store XML: {e}")

        logger.info(f"Successfully parsed {len(stores)} stores")
        return stores

    def parse_price_data(self, content: str) -> List[Dict[str, Any]]:

        prices = []

        try:
            # Check for BOM and remove if present
            if content.startswith('\ufeff'):
                content = content[1:]
                logger.debug("Removed BOM from content")

            root = ET.fromstring(content)

            # Get store ID - it's at the root level in Shufersal XML
            store_id = None
            for field in ['StoreId', 'StoreID', 'STOREID']:
                elem = root.find(field)  # Note: not .// for root level
                if elem is not None and elem.text:
                    store_id = str(int(elem.text.strip()))  # Remove leading zeros
                    break

            if not store_id:
                logger.warning("No store ID found in price file")
                return prices

            # Find the Items container first
            items_container = root.find('Items')
            if items_container is None:
                logger.warning("No Items container found in price file")
                return prices

            # Now find all Item elements within Items
            products = items_container.findall('Item')

            logger.info(f"Found {len(products)} products for store {store_id}")

            for product in products:
                try:
                    # Get barcode
                    barcode = None
                    for field in ['ItemCode', 'Barcode', 'ITEMCODE']:
                        elem = product.find(field)
                        if elem is not None and elem.text:
                            barcode = elem.text.strip()
                            break

                    if not barcode:
                        continue

                    # Get price
                    price = None
                    for field in ['ItemPrice', 'Price', 'ITEMPRICE']:
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
                    for field in ['ItemName', 'Name', 'ITEMNAME']:
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
                    logger.warning(f"Error parsing product: {e}")
                    continue

            logger.info(f"Successfully parsed {len(prices)} prices")

        except Exception as e:
            logger.error(f"Error parsing price XML: {e}")
            import traceback
            traceback.print_exc()

        return prices

    def _get_text(self, element, field_name: str, default: str = '') -> str:
        """Helper to safely get text from XML element"""
        elem = element.find(field_name)
        if elem is not None and elem.text:
            return elem.text.strip()
        return default

    def scrape_file_list(self, list_url: str, link_selector: Dict[str, str], file_type: str) -> List[str]:
        """Scrape file list from Shufersal website"""
        try:
            response = requests.get(list_url, timeout=30)
            if response.status_code != 200:
                logger.error(f"Failed to fetch {list_url}: {response.status_code}")
                return []

            soup = BeautifulSoup(response.text, 'html.parser')

            # Find download links
            links = soup.find_all(link_selector['tag'], string=link_selector['text'])
            file_urls = []

            for link in links:
                row = link.find_parent('tr')
                if not row:
                    continue

                # Get file name from the row
                cells = row.find_all('td')
                if len(cells) >= 2:
                    filename_cell = cells[1]
                    if file_type.lower() in filename_cell.text.lower():
                        href = link.get('href')
                        if href:
                            if not href.startswith('http'):
                                href = self.base_url + href
                            file_urls.append(href)

            logger.info(f"Found {len(file_urls)} {file_type} files")
            return file_urls

        except Exception as e:
            logger.error(f"Error scraping file list: {e}")
            return []
