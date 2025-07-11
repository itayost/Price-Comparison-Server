# utils/city_utils.py
"""
City name standardization utilities.
Used by parsers to ensure consistent city names.
"""

import logging

logger = logging.getLogger(__name__)


# Define the canonical city standardization rules
CITY_STANDARDIZATION_RULES = {
    # Tel Aviv variations
    'ת"א': 'תל אביב',
    'תל-אביב': 'תל אביב',
    'תל אביב-יפו': 'תל אביב',
    'תל אבית יפה': 'תל אביב',
    
    # Beer Sheva variations
    'באר-שבע': 'באר שבע',
    'בארשבע': 'באר שבע',
    
    # Other city variations
    'בית-שמש': 'בית שמש',
    'בני-ברק': 'בני ברק',
    'בת-ים': 'בת ים',
    'כפר-סבא': 'כפר סבא',
    'כפר סבא צפון': 'כפר סבא',
    'פתח-תקוה': 'פתח תקווה',
    'פתח-תקווה': 'פתח תקווה',
    'קריתאתא': 'קרית אתא',
    'קריית אתא': 'קרית אתא',
    'קרית חיים': 'חיפה',
    'רמת-גן': 'רמת גן',
    'רמתגן': 'רמת גן',
    'רמת-השרון': 'רמת השרון',
    'ראשל"צ': 'ראשון לציון',
    'רמת אביב א': 'תל אביב',
    'יקנעם': 'יוקנעם',
    'קרית טבעון': 'טבעון',
    'נצרת עלית': 'נצרת עילית',
    'פתח תקווה': 'פתח תקוה',  # Standardize to version without double vav
    'קריית גת': 'קרית גת',
    'קריית מוצקין': 'קרית מוצקין',
    
    # Handle unknown/empty
    'Unknown': 'לא ידוע',
    '': 'לא ידוע',
}


def standardize_city_name(city: str) -> str:
    """
    Standardize a city name according to our rules.
    
    Args:
        city: The city name to standardize
        
    Returns:
        The standardized city name
    """
    if not city:
        return 'לא ידוע'
    
    # Remove extra whitespace
    city = ' '.join(city.split()).strip()
    
    # Check if this city needs standardization
    if city in CITY_STANDARDIZATION_RULES:
        standardized = CITY_STANDARDIZATION_RULES[city]
        logger.debug(f"Standardized city: '{city}' -> '{standardized}'")
        return standardized
    
    # Return as-is if no rule applies
    return city


def get_city_variations(standardized_city: str) -> list:
    """
    Get all known variations of a standardized city name.
    
    Args:
        standardized_city: The standardized city name
        
    Returns:
        List of all known variations including the standardized name
    """
    variations = [standardized_city]
    
    # Find all variations that map to this standardized name
    for variant, standard in CITY_STANDARDIZATION_RULES.items():
        if standard == standardized_city and variant not in variations:
            variations.append(variant)
    
    return variations


def is_tel_aviv_variant(city: str) -> bool:
    """Check if a city name is a variant of Tel Aviv."""
    tel_aviv_variants = get_city_variations('תל אביב')
    return city in tel_aviv_variants


def is_standardized(city: str) -> bool:
    """Check if a city name is already standardized."""
    return city not in CITY_STANDARDIZATION_RULES
