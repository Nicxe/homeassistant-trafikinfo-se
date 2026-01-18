"""Constants for Trafikinfo SE."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

DOMAIN = "trafikinfo_se"

CONF_API_KEY = "api_key"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_MAX_ITEMS = "max_items"
CONF_MESSAGE_TYPES = "message_types"
CONF_LOCATION = "location"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_RADIUS_KM = "radius_km"

# Sorting / selection
CONF_SORT_MODE = "sort_mode"
CONF_SORT_LOCATION = "sort_location"

# Road filtering
CONF_FILTER_ROADS = "filter_roads"

SORT_MODE_RELEVANCE = "relevance"  # important -> nearest -> newest
SORT_MODE_NEAREST = "nearest"      # nearest -> newest
SORT_MODE_NEWEST = "newest"        # newest only

DEFAULT_SORT_MODE = SORT_MODE_RELEVANCE

# Filtering
CONF_FILTER_MODE = "filter_mode"
CONF_COUNTIES = "counties"
COUNTY_ALL = "all"

FILTER_MODE_COORDINATE = "coordinate"
FILTER_MODE_COUNTY = "county"
FILTER_MODE_SWEDEN = "sweden"

DEFAULT_SCAN_INTERVAL = timedelta(minutes=10)
DEFAULT_MAX_ITEMS = 25
DEFAULT_RADIUS_KM = 25.0
DEFAULT_FILTER_MODE = FILTER_MODE_COORDINATE
DEFAULT_COUNTIES: list[str] = [COUNTY_ALL]

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

# Dismissed events (user acknowledgment)
CONF_DISMISSED_EVENTS = "dismissed_events"

# Service names
SERVICE_DISMISS_EVENT = "dismiss_event"
SERVICE_RESTORE_EVENT = "restore_event"
SERVICE_RESTORE_ALL_EVENTS = "restore_all_events"

# Service attribute names
ATTR_ENTRY_ID = "entry_id"
ATTR_EVENT_KEY = "event_key"
ATTR_SIGNATURE = "signature"

ATTRIBUTION = "Data provided by Trafikverket (Trafikinfo)."


def get_user_agent(hass: "HomeAssistant | None" = None) -> str:
    """Generate User-Agent header for HTTP requests.

    Format: HomeAssistant/{ha_version} trafikinfo_se/{integration_version}
    """
    from homeassistant.const import __version__ as ha_version

    integration_version = "0.0.0"  # Updated by semantic-release
    return f"HomeAssistant/{ha_version} {DOMAIN}/{integration_version}"


# Swedish counties (län) using standard county codes.
# Trafikverket exposes affected counties per deviation as `CountyNo`.
COUNTIES: dict[str, str] = {
    "1": "Stockholms län",
    "3": "Uppsala län",
    "4": "Södermanlands län",
    "5": "Östergötlands län",
    "6": "Jönköpings län",
    "7": "Kronobergs län",
    "8": "Kalmar län",
    "9": "Gotlands län",
    "10": "Blekinge län",
    "12": "Skåne län",
    "13": "Hallands län",
    "14": "Västra Götalands län",
    "17": "Värmlands län",
    "18": "Örebro län",
    "19": "Västmanlands län",
    "20": "Dalarnas län",
    "21": "Gävleborgs län",
    "22": "Västernorrlands län",
    "23": "Jämtlands län",
    "24": "Västerbottens län",
    "25": "Norrbottens län",
}


