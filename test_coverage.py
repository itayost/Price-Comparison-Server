# Create a simpler test script
cat > test_coverage.py << 'EOF'
import sys
sys.path.append('.')

from database.connection import get_db
from database.new_models import Branch, BranchPrice, ChainProduct, Chain
from sqlalchemy import func

print("Testing database coverage...")

with get_db() as db:
    # Count stores by chain
    print("\n=== STORE COUNTS ===")
    store_counts = db.query(
        Chain.display_name,
        func.count(Branch.branch_id).label('stores')
    ).join(Branch).group_by(Chain.display_name).all()

    for chain, count in store_counts:
        print(f"{chain}: {count} stores")

    # Count prices by chain
    print("\n=== PRICE COUNTS ===")
    price_counts = db.query(
        Chain.display_name,
        func.count(BranchPrice.price_id).label('prices')
    ).join(ChainProduct).join(Branch).join(Chain).group_by(Chain.display_name).all()

    for chain, count in price_counts:
        print(f"{chain}: {count} prices")

    # Check Tel Aviv specifically
    print("\n=== TEL AVIV ANALYSIS ===")
    tel_aviv_stores = db.query(Branch).filter(
        Branch.city.in_(['תל אביב', 'תל-אביב', 'תל אבית יפה'])
    ).count()

    print(f"Total Tel Aviv stores: {tel_aviv_stores}")

    # Show stores by chain in Tel Aviv
    tel_aviv_by_chain = db.query(
        Chain.display_name,
        func.count(Branch.branch_id).label('stores')
    ).join(Branch).filter(
        Branch.city.in_(['תל אביב', 'תל-אביב', 'תל אבית יפה'])
    ).group_by(Chain.display_name).all()

    print("Tel Aviv stores by chain:")
    for chain, count in tel_aviv_by_chain:
        print(f"  {chain}: {count} stores")

print("Test completed!")
EOF

# Run it
python3 test_coverage.py
