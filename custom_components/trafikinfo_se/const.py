"""Constants for Trafikinfo SE."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "trafikinfo_se"

CONF_API_KEY = "api_key"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_MAX_ITEMS = "max_items"
CONF_MESSAGE_TYPES = "message_types"
CONF_LOCATION = "location"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_RADIUS_KM = "radius_km"

DEFAULT_SCAN_INTERVAL = timedelta(minutes=10)
DEFAULT_MAX_ITEMS = 25
DEFAULT_RADIUS_KM = 25.0

DEFAULT_MESSAGE_TYPES: list[str] = [
    "Viktig trafikinformation",
    "Hinder",
    "Olycka",
    "Restriktion",
    "Trafikmeddelande",
    "Vägarbete",
]

SITUATION_SCHEMA_VERSION = "1.6"

TRAFIKVERKET_DATACACHE_URL = "https://api.trafikinfo.trafikverket.se/v2/data.xml"
TRAFIKVERKET_ICONS_BASE_URL = "https://api.trafikinfo.trafikverket.se/v1/icons"
# v2 icon binary endpoint (used by the Icon dataset Url field)
TRAFIKVERKET_ICON_V2_URL_PREFIX = (
    "https://api.trafikinfo.trafikverket.se/v2/icons/data/road.infrastructure.icon/"
)

# Local icon cache (served by HA at /local/*)
ICON_CACHE_DIR = "trafikinfo_se/icons"

ATTRIBUTION = "Data provided by Trafikverket (Trafikinfo)."


