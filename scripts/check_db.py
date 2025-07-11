# Create: debug_victory.py
import sys
sys.path.append('.')

from database.connection import get_db
from database.new_models import Chain, Branch

def check_victory_cities():
    with get_db() as db:
        victory = db.query(Chain).filter(Chain.name == 'victory').first()

        print("=== VICTORY STORES BY CITY ===")
        victory_stores = db.query(Branch).filter(Branch.chain_id == victory.chain_id).all()

        cities = {}
        for store in victory_stores:
            city = store.city
            if city not in cities:
                cities[city] = []
            cities[city].append({
                'branch_id': store.branch_id,
                'store_id': store.store_id,
                'name': store.name
            })

        for city, stores in cities.items():
            print(f"\n{city}: {len(stores)} stores")
            for store in stores[:3]:  # Show first 3
                print(f"  - {store['store_id']}: {store['name']} (branch_id: {store['branch_id']})")

if __name__ == "__main__":
    check_victory_cities()
