"""
AgriIntel Configuration — Crop-specific settings and global constants.

To add a new crop, simply add a new entry to CROP_CONFIG.
No structural rewrite needed.
"""

# ─── Global settings ──────────────────────────────────────────────
# Set to True to skip all external API calls and use bundled data only.
# This avoids timeouts when FAOSTAT / World Bank / NASA POWER are down.
USE_BUNDLED_DATA = True

COUNTRY = "France"
COUNTRY_ISO3 = "FRA"
FAOSTAT_AREA_CODE = 68  # France

# 3×3 sample grid across France for weather aggregation (lat, lon)
FRANCE_WEATHER_GRID = [
    (43.6, 1.4),   # SW  — Toulouse area
    (43.6, 3.9),   # S   — Montpellier area
    (43.6, 6.1),   # SE  — Provence
    (46.2, 0.3),   # W   — Poitiers area
    (46.2, 2.5),   # C   — Clermont-Ferrand area
    (46.2, 4.8),   # E   — Lyon area
    (48.8, 1.5),   # NW  — Chartres / Beauce
    (48.8, 3.0),   # N   — Champagne
    (48.8, 5.5),   # NE  — Lorraine
]

# ─── WMS / CLMS settings ─────────────────────────────────────────
CLMS_WMS_URL = "https://geoserver.vlcc.geoville.com/geoserver/ows"
CLMS_LAYER_TEMPLATE = "HRL_CPL:CTY_S{year}"
CLMS_DEFAULT_YEAR = 2021

# ─── Sentinel-2 / Planetary Computer ─────────────────────────────
PLANETARY_COMPUTER_STAC = (
    "https://planetarycomputer.microsoft.com/api/stac/v1"
)
S2_COLLECTION = "sentinel-2-l2a"
S2_MAX_CLOUD_COVER = 15  # percent

# ─── Default bounding box for France (overview) ──────────────────
FRANCE_BBOX = [-5.14, 41.33, 9.56, 51.09]  # [west, south, east, north]

# ─── NASA POWER ──────────────────────────────────────────────────
NASA_POWER_BASE = "https://power.larc.nasa.gov/api/temporal/daily/point"
POWER_PARAMETERS = ["PRECTOTCORR", "T2M", "T2M_MAX"]

# ─── FAOSTAT ─────────────────────────────────────────────────────
FAOSTAT_BASE = "https://www.fao.org/faostat/en/#data/QCL"

# ─── World Bank Pink Sheet ───────────────────────────────────────
WORLDBANK_COMMODITIES_URL = (
    "https://thedocs.worldbank.org/en/doc/"
    "5d903e848db1d8a6bef3c550bbbcabb5-0050012024/related/"
    "CMO-Historical-Data-Monthly.xlsx"
)

# ─── Crop Configuration ─────────────────────────────────────────
CROP_CONFIG = {
    "wheat": {
        "faostat_item_code": 15,          # Wheat
        "faostat_element_code": 5510,     # Yield (hg/ha)
        "growing_season_months": [10, 11, 12, 1, 2, 3, 4, 5, 6],
        "price_series_name": "Wheat",
        "ndvi_peak_months": [4, 5, 6],   # April–June
        "description": "Common wheat — France's largest arable crop",
    },
    "maize": {
        "faostat_item_code": 56,
        "faostat_element_code": 5510,
        "growing_season_months": [4, 5, 6, 7, 8, 9],
        "price_series_name": "Maize",
        "ndvi_peak_months": [7, 8],
        "description": "Grain maize — key summer crop",
    },
    "grape": {
        "faostat_item_code": 560,
        "faostat_element_code": 5510,
        "growing_season_months": [3, 4, 5, 6, 7, 8, 9],
        "price_series_name": "Grapes",
        "ndvi_peak_months": [6, 7, 8],
        "description": "Wine grapes — viticulture forecast",
    },
}

DEFAULT_CROP = "wheat"
