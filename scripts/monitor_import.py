# scripts/monitor_import.py

import psutil
import time
import threading
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class ImportMonitor:
    """Monitor import performance and system resources"""
    
    def __init__(self):
        self.start_time = time.time()
        self.running = True
        self.process = psutil.Process()
        
    def start(self):
        """Start monitoring in background thread"""
        thread = threading.Thread(target=self._monitor_loop, daemon=True)
        thread.start()
    
    def stop(self):
        """Stop monitoring"""
        self.running = False
    
    def _monitor_loop(self):
        """Monitor loop"""
        while self.running:
            try:
                # CPU and memory usage
                cpu_percent = self.process.cpu_percent(interval=1)
                memory_info = self.process.memory_info()
                memory_mb = memory_info.rss / 1024 / 1024
                
                # Database connections (if available)
                connections = self._get_db_connections()
                
                # Log status
                elapsed = time.time() - self.start_time
                logger.info(
                    f"Monitor - Time: {elapsed:.0f}s | "
                    f"CPU: {cpu_percent:.1f}% | "
                    f"Memory: {memory_mb:.0f}MB | "
                    f"DB Connections: {connections}"
                )
                
                # Alert if memory is too high
                if memory_mb > 2000:
                    logger.warning(f"High memory usage: {memory_mb:.0f}MB")
                
                time.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                logger.error(f"Monitor error: {e}")
    
    def _get_db_connections(self):
        """Get active database connections"""
        try:
            from database.connection_optimized import engine
            return engine.pool.size()
        except:
            return "N/A" 
