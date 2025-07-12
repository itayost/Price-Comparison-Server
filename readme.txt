# 🛒 Israeli Supermarket Price Comparison Server

A modern, production-ready REST API server for comparing grocery prices across major supermarket chains in Israel. Built with FastAPI, supports both SQLite and Oracle databases, and features automated data scraping from Shufersal and Victory stores.

## 🌟 Key Features

### 🏪 Core Functionality
- **Real-time Price Comparison**: Compare product prices across Shufersal and Victory stores
- **Smart Cart Optimization**: Find the cheapest store for your entire shopping cart
- **Location-Based Search**: Search products and stores by city (supports Hebrew and English)
- **Barcode Lookup**: Look up products using exact barcodes
- **Price Statistics**: View min/max/average prices and potential savings

### 👤 User Management
- **JWT-based Authentication**: Secure user registration and login
- **Saved Shopping Carts**: Save and manage multiple shopping lists
- **Cart Persistence**: Access your carts from any device

### 🔧 Technical Features
- **RESTful API**: Clean, documented API endpoints with auto-generated Swagger docs
- **Dual Database Support**: SQLite for development, Oracle Autonomous Database for production
- **Automated Data Import**: Multi-threaded scraping and import from supermarket websites
- **Production Ready**: Includes Docker support, CI/CD, and deployment configurations
- **Comprehensive Testing**: Full test suite with pytest and coverage reporting

## 📋 Requirements

- **Python**: 3.10 or higher
- **Database**: SQLite (development) or Oracle Autonomous Database (production)
- **Memory**: 4GB+ RAM recommended for data import operations
- **Storage**: 2GB+ for price data cache

## 🚀 Quick Start

### 1. Clone and Setup
```bash
git clone <your-repository-url>
cd price_comparison_server

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Environment Configuration
Create a `.env` file in the project root:

```env
# === Basic Configuration ===
SECRET_KEY=your-secret-key-change-in-production
HOST=0.0.0.0
PORT=8000

# === Database Configuration ===
USE_ORACLE=false
DATABASE_URL=sqlite:///./price_comparison.db

# === Oracle Configuration (if USE_ORACLE=true) ===
ORACLE_USER=ADMIN
ORACLE_PASSWORD=your-oracle-password
ORACLE_SERVICE=your_service_name
ORACLE_WALLET_DIR=./wallet
ORACLE_WALLET_PASSWORD=your-wallet-password

# === Import Configuration ===
AUTO_IMPORT=false  # Set to true for automatic data import
IMPORT_LIMIT=0     # Limit files during import (0 = no limit)

# === Development ===
RELOAD=true
SQL_ECHO=false
TESTING=false
```

### 3. Start the Server

**Option A: Automatic Setup (Recommended)**
```bash
python main.py
```
The server will automatically:
- Initialize the database and create tables
- Start the API server on http://localhost:8000
- (Optional) Import data if `AUTO_IMPORT=true`

**Option B: Manual Setup**
```bash
# Initialize database
python database/connection.py

# Import store data
python scripts/import_chain_data.py --stores-only

# Import price data (start with limited files for testing)
python scripts/import_prices.py --limit 5

# Start server
python main.py
```

### 4. Test the API
Visit http://localhost:8000/docs for interactive API documentation, or test with curl:

```bash
# Check health
curl http://localhost:8000/health

# Search for products
curl "http://localhost:8000/api/products/search?query=חלב&city=תל אביב"

# Compare cart prices
curl -X POST "http://localhost:8000/api/cart/compare" \
  -H "Content-Type: application/json" \
  -d '{
    "city": "תל אביב",
    "items": [
      {"barcode": "7290000000001", "quantity": 2}
    ]
  }'
```

## 📚 API Documentation

### 🔗 Interactive Documentation
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI Schema**: http://localhost:8000/openapi.json

### 📝 Key Endpoints

#### Authentication (`/api/auth`)
```bash
# Register new user
POST /api/auth/register
{
  "email": "user@example.com",
  "password": "secure_password"
}

# Login
POST /api/auth/login
{
  "email": "user@example.com", 
  "password": "secure_password"
}

# Get user info (requires auth)
GET /api/auth/me
Headers: Authorization: Bearer <token>
```

#### Product Search (`/api/products`)
```bash
# Search products by name
GET /api/products/search?query=חלב&city=תל אביב&limit=20

# Get product by barcode
GET /api/products/barcode/7290000000001?city=תל אביב

# List all cities
GET /api/products/cities

# List all chains
GET /api/products/chains
```

#### Cart Comparison (`/api/cart`)
```bash
# Compare cart prices across all stores
POST /api/cart/compare
{
  "city": "תל אביב",
  "items": [
    {"barcode": "7290000000001", "quantity": 2},
    {"barcode": "7290000000002", "quantity": 1}
  ]
}

# Get sample cart for testing
GET /api/cart/sample
```

#### Saved Carts (`/api/saved-carts`) - Requires Authentication
```bash
# Save a cart
POST /api/saved-carts/save
{
  "cart_name": "Weekly Shopping",
  "city": "תל אביב",
  "items": [{"barcode": "7290000000001", "quantity": 2}]
}

# List user's saved carts
GET /api/saved-carts/list

# Get specific cart
GET /api/saved-carts/{cart_id}

# Compare saved cart with current prices
GET /api/saved-carts/{cart_id}/compare
```

#### System Information (`/api/system`)
```bash
# Detailed health check
GET /api/system/health/detailed

# Database statistics
GET /api/system/statistics
```

## 🏗️ Project Architecture

```
price_comparison_server/
├── 📁 database/              # Database layer
│   ├── connection.py         # Database connections & config
│   ├── new_models.py         # SQLAlchemy models
│   └── startup.py           # Database initialization
│
├── 📁 routes/               # API endpoints
│   ├── auth_routes.py       # Authentication endpoints
│   ├── cart_routes.py       # Cart comparison endpoints
│   ├── product_routes.py    # Product search endpoints
│   ├── saved_carts_routes.py # Saved carts endpoints
│   └── system_routes.py     # System/health endpoints
│
├── 📁 services/             # Business logic
│   ├── auth_service.py      # User authentication logic
│   ├── cart_service.py      # Cart comparison algorithms
│   ├── product_search_service.py # Product search logic
│   └── saved_carts_service.py # Saved carts management
│
├── 📁 parsers/              # Data scrapers
│   ├── base_parser.py       # Abstract parser base class
│   ├── shufersal_parser.py  # Shufersal XML parser
│   ├── victory_parser.py    # Victory XML parser
│   └── __init__.py          # Parser registry
│
├── 📁 scripts/              # Utility scripts
│   ├── import_chain_data.py # Import store information
│   └── import_prices.py     # Import price data
│
├── 📁 tests/               # Test suite
│   ├── conftest.py         # Test configuration
│   ├── test_api.py         # API endpoint tests
│   └── test_services.py    # Business logic tests
│
├── 📁 .github/workflows/   # CI/CD configuration
│   └── tests.yml           # Automated testing
│
├── main.py                 # FastAPI application entry point
├── requirements.txt        # Python dependencies
├── .env.example           # Environment configuration template
├── .coveragerc           # Coverage configuration
└── railway.json          # Railway deployment config
```

## 🗄️ Database Schema

### Core Tables
- **chains**: Supermarket chains (שופרסל, ויקטורי)
- **branches**: Store locations with addresses and cities
- **chain_products**: Products specific to each chain (handles different naming)
- **branch_prices**: Current prices at each store branch

### User Tables
- **users**: Registered users with secure password hashing
- **saved_carts**: User's saved shopping lists stored as JSON

### Key Features
- **Normalized Design**: Eliminates data duplication
- **Unicode Support**: Full Hebrew text support
- **Efficient Indexing**: Optimized for fast searches
- **Oracle/SQLite Compatible**: Same schema works on both databases

## 🔄 Data Import System

The system includes sophisticated parsers for scraping price data:

### Import Commands
```bash
# Import everything (stores + prices)
python scripts/import_chain_data.py
python scripts/import_prices.py

# Import specific chain
python scripts/import_chain_data.py --chain shufersal
python scripts/import_prices.py --chain shufersal --limit 10

# Import only store information (fast)
python scripts/import_chain_data.py --stores-only

# Large-scale import with progress tracking
python scripts/import_prices.py --workers 4
```

### Import Features
- **Multi-threaded Processing**: Parallel file processing for speed
- **Progress Tracking**: Real-time progress with detailed logging
- **Error Handling**: Continues on errors, logs all issues
- **Data Validation**: Validates prices and product information
- **Incremental Updates**: Updates existing products, adds new ones
- **Memory Efficient**: Processes large files without memory issues

### Data Sources
- **Shufersal**: SAP/ABAP XML format with Hebrew encoding
- **Victory**: Standard XML with different structure
- **File Types**: Compressed .gz files with store and price data
- **Update Frequency**: Daily updates from supermarket websites

## 🧪 Testing

### Run Tests
```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_api.py -v

# Run specific test case
pytest tests/test_api.py::TestMainFeatures::test_search_products -v
```

### Test Coverage
- **API Endpoints**: All routes tested with various scenarios
- **Business Logic**: Service layer unit tests
- **Database Operations**: Model and query testing
- **Authentication**: JWT token validation and security
- **Error Handling**: Edge cases and error conditions

### Test Features
- **Isolated Database**: Each test uses a clean database
- **Mock Data**: Realistic test data with Hebrew text
- **API Testing**: Full request/response cycle testing
- **Coverage Reporting**: HTML reports in `htmlcov/`

## 🚀 Deployment

### Local Network Access
```bash
# Server accessible from mobile devices on same network
python main.py  # Runs on 0.0.0.0:8000
```
Access from other devices: `http://YOUR_LOCAL_IP:8000`

### Production Deployment

#### Railway (Recommended)
```bash
# Deploy to Railway
railway login
railway up
```

#### Oracle Cloud Setup
1. Create Oracle Autonomous Database
2. Download wallet files to `./wallet/`
3. Configure Oracle credentials in `.env`
4. Set `USE_ORACLE=true`

#### Environment Variables for Production
```env
USE_ORACLE=true
AUTO_IMPORT=true
IMPORT_LIMIT=50
SECRET_KEY=<strong-production-key>
```

## 🛠️ Development

### Adding a New Supermarket Chain

1. **Create Parser**:
```python
# parsers/newchain_parser.py
from .base_parser import BaseChainParser

class NewChainParser(BaseChainParser):
    def __init__(self):
        super().__init__('newchain', 'NC')
    
    def parse_stores_data(self, content):
        # Implementation for store data
        pass
    
    def parse_price_data(self, content):
        # Implementation for price data
        pass
```

2. **Register Parser**:
```python
# parsers/__init__.py
from .newchain_parser import NewChainParser
PARSER_REGISTRY['newchain'] = NewChainParser
```

3. **Import Data**:
```bash
python scripts/import_chain_data.py --chain newchain
```

### API Development Tips
- FastAPI auto-reloads on code changes during development
- Test new endpoints immediately at `/docs`
- Use Pydantic models for request/response validation
- Follow existing patterns for consistency

### Database Migrations
```python
# For schema changes, modify database/new_models.py
# Then recreate tables (development only):
python -c "
from database.connection import engine
from database.new_models import Base
Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)
"
```

## 🐛 Troubleshooting

### Common Issues

**1. No products found in searches**
```bash
# Check if data is imported
curl http://localhost:8000/api/system/statistics

# Import data if needed
python scripts/import_chain_data.py --stores-only
python scripts/import_prices.py --limit 5
```

**2. Database connection errors**
```bash
# Check database file permissions (SQLite)
ls -la *.db

# Verify Oracle connection (if using Oracle)
python -c "from database.connection import engine; print(engine.execute('SELECT 1 FROM DUAL').fetchone())"
```

**3. City not found errors**
```bash
# Check available cities
curl http://localhost:8000/api/products/cities

# Cities are case-sensitive and may be in Hebrew
```

**4. Import script errors**
```bash
# Run with debug logging
python scripts/import_prices.py --limit 1 --debug

# Check available disk space
df -h .

# Verify internet connection for scraping
curl -I https://prices.shufersal.co.il
```

**5. Authentication issues**
```bash
# Check token expiration (tokens expire in 24 hours)
# Re-login to get a new token

# Verify JWT secret in .env
echo $SECRET_KEY
```

### Performance Optimization

**For Large Imports**:
```bash
# Use more workers for faster processing
python scripts/import_prices.py --workers 8

# Limit import for testing
python scripts/import_prices.py --limit 20
```

**For API Performance**:
- Use city filters in product searches
- Limit result sets with `limit` parameter
- Consider adding Redis caching for production

## 📄 License

This project is developed as a university Software Engineering final project. Please respect academic integrity guidelines when using this code.

## 🤝 Contributing

This is a university project, but suggestions and feedback are welcome:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📧 Contact

For questions about this project, please contact [your-email@university.edu].

---

**Note**: This server requires active internet connection for data scraping. Supermarket websites may change their structure, requiring parser updates. The system is designed for educational purposes and research into price comparison algorithms.
