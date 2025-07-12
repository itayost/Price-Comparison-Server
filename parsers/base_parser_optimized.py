# parsers/base_parser_optimized.py

from abc import ABC, abstractmethod
import logging
from typing import List, Dict, Any, Optional, Generator
import gzip
import requests
from datetime import datetime
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
import io

logger = logging.getLogger(__name__)

class OptimizedBaseParser(BaseChainParser):
    """Optimized base parser with streaming and chunking support"""
    
    def __init__(self, chain_name: str, chain_code: str):
        super().__init__(chain_name, chain_code)
        self.chunk_size = 10000  # Process XML in chunks
        
    def download_file_stream(self, url: str) -> Optional[io.BytesIO]:
        """Download file with streaming for memory efficiency"""
        try:
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()
            
            # Stream to memory
            content = io.BytesIO()
            for chunk in response.iter_content(chunk_size=8192):
                content.write(chunk)
            
            content.seek(0)
            
            # Handle gzip if needed
            if url.endswith('.gz'):
                content = gzip.GzipFile(fileobj=content)
            
            return content
            
        except Exception as e:
            logger.error(f"Error downloading {url}: {e}")
            return None
    
    def parse_price_data_streaming(self, content: io.BytesIO) -> Generator[Dict[str, Any], None, None]:
        """Parse price data with streaming for memory efficiency"""
        # This should be overridden by specific parsers
        # Example implementation for streaming XML parsing
        
        parser = ET.iterparse(content, events=['start', 'end'])
        parser = iter(parser)
        event, root = next(parser)
        
        store_id = None
        current_item = {}
        
        for event, elem in parser:
            if event == 'end':
                if elem.tag == 'StoreId' and store_id is None:
                    store_id = elem.text.strip()
                    
                elif elem.tag in ['Product', 'Item']:
                    # Extract product data
                    if current_item.get('barcode') and current_item.get('price'):
                        current_item['store_id'] = store_id
                        yield current_item
                    
                    current_item = {}
                    elem.clear()  # Free memory
                    
                elif elem.tag == 'ItemCode':
                    current_item['barcode'] = elem.text.strip() if elem.text else None
                    
                elif elem.tag == 'ItemName':
                    current_item['name'] = elem.text.strip() if elem.text else None
                    
                elif elem.tag == 'ItemPrice':
                    try:
                        current_item['price'] = float(elem.text.strip())
                    except:
                        pass
        
        root.clear()  # Final cleanup
