"""RoadCondition support for Trafikinfo SE."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_API_KEY,
    CONF_COUNTIES,
    CONF_FILTER_MODE,
    CONF_FILTER_ROADS,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MAX_ITEMS,
    CONF_RADIUS_KM,
    CONF_SORT_LOCATION,
    COUNTY_ALL,
    DEFAULT_FILTER_MODE,
    DEFAULT_MAX_ITEMS,
    DEFAULT_RADIUS_KM,
    DEFAULT_ROAD_CONDITION_SCAN_INTERVAL,
    DOMAIN,
    FILTER_MODE_COORDINATE,
    FILTER_MODE_COUNTY,
    ROAD_CONDITION_SCHEMA_VERSION,
    TRAFIKVERKET_DATACACHE_URL,
    get_user_agent,
)
from .coordinator import (
    TrafikinfoAPIError,
    TrafikinfoAuthenticationError,
    TrafikinfoError,
    TrafikinfoParseError,
)

_LOGGER = logging.getLogger(__name__)

ROAD_CONDITION_NO_DATA = "no_data"
ROAD_CONDITION_NORMAL = "normal"
ROAD_CONDITION_DIFFICULT = "difficult"
ROAD_CONDITION_VERY_DIFFICULT = "very_difficult"
ROAD_CONDITION_ICE_SNOW = "ice_snow"
ROAD_CONDITION_UNKNOWN = "unknown"

ROAD_CONDITION_STATES = [
    ROAD_CONDITION_NO_DATA,
    ROAD_CONDITION_NORMAL,
    ROAD_CONDITION_DIFFICULT,
    ROAD_CONDITION_VERY_DIFFICULT,
    ROAD_CONDITION_ICE_SNOW,
    ROAD_CONDITION_UNKNOWN,
]

_STATE_BY_CODE = {
    1: ROAD_CONDITION_NORMAL,
    2: ROAD_CONDITION_DIFFICULT,
    3: ROAD_CONDITION_VERY_DIFFICULT,
    4: ROAD_CONDITION_ICE_SNOW,
}
_WKT_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _strip(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _as_int(value: str | None) -> int | None:
    value = _strip(value)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: str | None) -> bool | None:
    value = _strip(value)
    if value is None:
        return None
    if value.lower() in ("true", "1", "yes"):
        return True
    if value.lower() in ("false", "0", "no"):
        return False
    return None


def _as_dt(value: str | None) -> datetime | None:
    value = _strip(value)
    if value is None:
        return None
    return dt_util.parse_datetime(value)


def _text_list(element: ET.Element, name: str) -> list[str]:
    values: list[str] = []
    for child in element.findall(f"./{{*}}{name}"):
        value = _strip(child.text)
        if value is not None:
            values.append(value)
    return values


def road_condition_state(condition_code: int | None) -> str:
    """Return a stable Home Assistant state for a Trafikverket condition code."""
    if condition_code is None:
        return ROAD_CONDITION_UNKNOWN
    return _STATE_BY_CODE.get(condition_code, ROAD_CONDITION_UNKNOWN)


@dataclass(frozen=True, slots=True)
class RoadCondition:
    """One active Trafikverket RoadCondition road segment."""

    condition_id: str
    condition_code: int | None
    condition_text: str | None
    condition_info: list[str]
    causes: list[str]
    warnings: list[str]
    measures: list[str]
    county_no: list[int]
    creator: str | None
    icon_id: str | None
    location_text: str | None
    road_number: str | None
    road_number_numeric: int | None
    safety_related_message: bool | None
    start_time: datetime | None
    end_time: datetime | None
    modified_time: datetime | None
    geometry_wgs84: str | None

    @property
    def state(self) -> str:
        return road_condition_state(self.condition_code)

    @property
    def is_hazardous(self) -> bool:
        return self.condition_code is not None and self.condition_code > 1

    def signature(self) -> str:
        """Return a stable change signature for event publication."""
        return "|".join(
            (
                str(self.condition_code or ""),
                self.condition_text or "",
                ",".join(self.condition_info),
                ",".join(self.causes),
                ",".join(self.warnings),
                ",".join(self.measures),
                self.modified_time.isoformat() if self.modified_time else "",
                self.end_time.isoformat() if self.end_time else "",
            )
        )

    def as_dict(self, *, distance_km: float | None = None) -> dict[str, Any]:
        """Return stable user-facing state attributes."""

        def _dt(value: datetime | None) -> str | None:
            return value.isoformat() if value is not None else None

        return {
            "id": self.condition_id,
            "state": self.state,
            "condition_code": self.condition_code,
            "condition_text": self.condition_text,
            "condition_info": list(self.condition_info),
            "causes": list(self.causes),
            "warnings": list(self.warnings),
            "measures": list(self.measures),
            "county_no": list(self.county_no),
            "creator": self.creator,
            "icon_id": self.icon_id,
            "location_text": self.location_text,
            "road_number": self.road_number,
            "road_number_numeric": self.road_number_numeric,
            "safety_related_message": self.safety_related_message,
            "start_time": _dt(self.start_time),
            "end_time": _dt(self.end_time),
            "modified_time": _dt(self.modified_time),
            "geometry_wgs84": self.geometry_wgs84,
            "distance_km": round(distance_km, 2) if distance_km is not None else None,
        }


@dataclass(frozen=True, slots=True)
class RoadConditionSnapshot:
    """Filtered current RoadCondition state for one config entry."""

    conditions: list[RoadCondition]
    worst_state: str
    hazardous_count: int
    total_count: int
    last_modified: datetime | None
    last_change_id: str | None


def _snapshot(
    conditions: list[RoadCondition],
    *,
    last_modified: datetime | None = None,
    last_change_id: str | None = None,
) -> RoadConditionSnapshot:
    known = [item for item in conditions if item.condition_code in _STATE_BY_CODE]
    if known:
        worst = max(known, key=lambda item: int(item.condition_code or 0)).state
    elif conditions:
        worst = ROAD_CONDITION_UNKNOWN
    else:
        worst = ROAD_CONDITION_NO_DATA
    return RoadConditionSnapshot(
        conditions=conditions,
        worst_state=worst,
        hazardous_count=sum(item.is_hazardous for item in conditions),
        total_count=len(conditions),
        last_modified=last_modified,
        last_change_id=last_change_id,
    )


def build_road_condition_request_xml(api_key: str, *, limit: int = 2000) -> str:
    """Build a filtered request for current RoadCondition records."""
    includes = (
        "Cause",
        "ConditionCode",
        "ConditionInfo",
        "ConditionText",
        "CountyNo",
        "Creator",
        "Deleted",
        "EndTime",
        "Geometry",
        "IconId",
        "Id",
        "LocationText",
        "Measure",
        "ModifiedTime",
        "RoadNumber",
        "RoadNumberNumeric",
        "SafetyRelatedMessage",
        "StartTime",
        "Warning",
    )
    include_xml = "".join(f"<INCLUDE>{field}</INCLUDE>" for field in includes)
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<REQUEST>"
        f'<LOGIN authenticationkey="{api_key}" />'
        f'<QUERY objecttype="RoadCondition" namespace="Road.TrafficInfo" '
        f'schemaversion="{ROAD_CONDITION_SCHEMA_VERSION}" limit="{int(limit)}">'
        '<FILTER><AND><EQ name="Deleted" value="false" /></AND></FILTER>'
        f"{include_xml}"
        "</QUERY>"
        "</REQUEST>"
    )


def parse_road_condition_response(
    xml_text: str, *, now: datetime | None = None
) -> RoadConditionSnapshot:
    """Parse active RoadCondition records and API metadata."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as err:
        raise TrafikinfoParseError(f"Invalid XML from Trafikverket: {err}") from err

    error_message = _strip(root.findtext(".//{*}ERROR/{*}MESSAGE"))
    if error_message:
        lowered = error_message.lower()
        if "authentication" in lowered or "invalid key" in lowered:
            raise TrafikinfoAuthenticationError(
                f"Authentication failed: {error_message}"
            )
        raise TrafikinfoAPIError(f"Trafikverket API error: {error_message}")

    current_time = now or dt_util.utcnow()
    conditions: list[RoadCondition] = []
    for element in root.findall(".//{*}RoadCondition"):
        if _as_bool(element.findtext("./{*}Deleted")) is True:
            continue

        start_time = _as_dt(element.findtext("./{*}StartTime"))
        end_time = _as_dt(element.findtext("./{*}EndTime"))
        if start_time is not None and start_time > current_time:
            continue
        if end_time is not None and end_time < current_time:
            continue

        condition_id = _strip(element.findtext("./{*}Id"))
        if not condition_id:
            continue
        county_no = [
            value
            for value in (
                _as_int(node.text) for node in element.findall("./{*}CountyNo")
            )
            if value is not None
        ]
        conditions.append(
            RoadCondition(
                condition_id=condition_id,
                condition_code=_as_int(element.findtext("./{*}ConditionCode")),
                condition_text=_strip(element.findtext("./{*}ConditionText")),
                condition_info=_text_list(element, "ConditionInfo"),
                causes=_text_list(element, "Cause"),
                warnings=_text_list(element, "Warning"),
                measures=_text_list(element, "Measure"),
                county_no=county_no,
                creator=_strip(element.findtext("./{*}Creator")),
                icon_id=_strip(element.findtext("./{*}IconId")),
                location_text=_strip(element.findtext("./{*}LocationText")),
                road_number=_strip(element.findtext("./{*}RoadNumber")),
                road_number_numeric=_as_int(element.findtext("./{*}RoadNumberNumeric")),
                safety_related_message=_as_bool(
                    element.findtext("./{*}SafetyRelatedMessage")
                ),
                start_time=start_time,
                end_time=end_time,
                modified_time=_as_dt(element.findtext("./{*}ModifiedTime")),
                geometry_wgs84=_strip(element.findtext(".//{*}Geometry//{*}WGS84")),
            )
        )

    conditions.sort(
        key=lambda item: (
            item.condition_code or 0,
            item.modified_time or datetime.min.replace(tzinfo=dt_util.UTC),
            item.condition_id,
        ),
        reverse=True,
    )
    last_modified_element = root.find(".//{*}INFO/{*}LASTMODIFIED")
    last_modified = None
    if last_modified_element is not None:
        last_modified = _as_dt(last_modified_element.attrib.get("datetime"))
    return _snapshot(
        conditions,
        last_modified=last_modified,
        last_change_id=_strip(root.findtext(".//{*}INFO/{*}LASTCHANGEID")),
    )


class RoadConditionCoordinator(DataUpdateCoordinator[RoadConditionSnapshot]):
    """Fetch and filter Trafikverket RoadCondition data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry = entry
        self._api_key = str(entry.data.get(CONF_API_KEY, "")).strip()
        self._filter_mode = str(
            entry.options.get(
                CONF_FILTER_MODE, entry.data.get(CONF_FILTER_MODE, DEFAULT_FILTER_MODE)
            )
        )
        if self._filter_mode not in (FILTER_MODE_COORDINATE, FILTER_MODE_COUNTY):
            self._filter_mode = DEFAULT_FILTER_MODE
        raw_counties = entry.options.get(
            CONF_COUNTIES, entry.data.get(CONF_COUNTIES, [])
        )
        self._counties = (
            {str(value) for value in raw_counties if str(value).strip()}
            if isinstance(raw_counties, list)
            else set()
        )
        if self._filter_mode == FILTER_MODE_COUNTY and not self._counties:
            self._counties = {COUNTY_ALL}
        raw_roads = entry.options.get(
            CONF_FILTER_ROADS, entry.data.get(CONF_FILTER_ROADS, [])
        )
        if isinstance(raw_roads, str):
            raw_roads = re.split(r"[;,]", raw_roads)
        self._filter_roads = (
            [str(value).strip() for value in raw_roads if str(value).strip()]
            if isinstance(raw_roads, list)
            else []
        )
        self._latitude = float(
            entry.options.get(
                CONF_LATITUDE, entry.data.get(CONF_LATITUDE, hass.config.latitude)
            )
        )
        self._longitude = float(
            entry.options.get(
                CONF_LONGITUDE, entry.data.get(CONF_LONGITUDE, hass.config.longitude)
            )
        )
        self._radius_km = float(
            entry.options.get(
                CONF_RADIUS_KM, entry.data.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM)
            )
        )
        if self._filter_mode == FILTER_MODE_COUNTY:
            sort_location = entry.options.get(
                CONF_SORT_LOCATION, entry.data.get(CONF_SORT_LOCATION)
            )
            if isinstance(sort_location, dict):
                self._latitude = float(
                    sort_location.get("latitude", hass.config.latitude)
                )
                self._longitude = float(
                    sort_location.get("longitude", hass.config.longitude)
                )
        self._max_items = int(
            entry.options.get(
                CONF_MAX_ITEMS, entry.data.get(CONF_MAX_ITEMS, DEFAULT_MAX_ITEMS)
            )
        )
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_road_condition",
            update_interval=DEFAULT_ROAD_CONDITION_SCAN_INTERVAL,
            always_update=False,
            config_entry=entry,
        )

    @property
    def max_items(self) -> int:
        return self._max_items

    @property
    def filter_mode(self) -> str:
        return self._filter_mode

    @property
    def counties(self) -> list[str]:
        return sorted(self._counties)

    @property
    def filter_roads(self) -> list[str]:
        return list(self._filter_roads)

    @property
    def latitude(self) -> float:
        return self._latitude

    @property
    def longitude(self) -> float:
        return self._longitude

    @property
    def radius_km(self) -> float:
        return self._radius_km

    @staticmethod
    def _normalize_road(value: str | None) -> str:
        normalized = str(value or "").strip().lower()
        normalized = re.sub(r"^(väg|vag|road)\s+", "", normalized)
        normalized = re.sub(r"\b([a-z])\s+(?=\d)", r"\1", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    def _road_identifiers(self, condition: RoadCondition) -> set[str]:
        raw_road = str(condition.road_number or "").strip()
        identifiers = {self._normalize_road(raw_road)} if raw_road else set()
        if condition.road_number_numeric is not None:
            identifiers.add(str(condition.road_number_numeric))
        for match in re.finditer(
            r"(?:väg|vag|road)\s*([a-z]?\s*\d+(?:\.\d+)?)",
            raw_road,
            flags=re.IGNORECASE,
        ):
            identifiers.add(self._normalize_road(match.group(1)))
        return {identifier for identifier in identifiers if identifier}

    def _road_matches(self, condition: RoadCondition) -> bool:
        if not self._filter_roads:
            return True
        road_identifiers = self._road_identifiers(condition)
        location = re.sub(
            r"\s+", " ", str(condition.location_text or "").strip().lower()
        )
        for raw_token in self._filter_roads:
            token = self._normalize_road(raw_token)
            if not token:
                continue
            if token.endswith("*") and token.count("*") == 1:
                prefix = token[:-1].strip()
                if prefix and any(
                    identifier.startswith(prefix) for identifier in road_identifiers
                ):
                    return True
                continue
            if "*" in token:
                continue
            if any(char.isdigit() for char in token):
                if token in road_identifiers:
                    return True
                continue
            if token in location:
                return True
        return False

    @staticmethod
    def _wkt_points(wkt: str | None) -> list[tuple[float, float]]:
        if not isinstance(wkt, str) or not wkt.strip():
            return []
        header = wkt.split("(", 1)[0].upper()
        step = 3 if " Z" in header or header.endswith("Z") else 2
        values = [float(value) for value in _WKT_NUMBER_RE.findall(wkt)]
        return [
            (values[index], values[index + 1])
            for index in range(0, len(values) - 1, step)
        ]

    @staticmethod
    def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
        radius = 6371.0
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)
        value = (
            math.sin(delta_lat / 2) ** 2
            + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
        )
        return 2 * radius * math.asin(math.sqrt(value))

    def distance_km(self, condition: RoadCondition) -> float | None:
        """Return minimum distance from configured center to the segment."""
        points = self._wkt_points(condition.geometry_wgs84)
        if not points:
            return None
        return min(
            self._haversine_km(self._longitude, self._latitude, lon, lat)
            for lon, lat in points[:200]
        )

    def _in_scope(self, condition: RoadCondition) -> bool:
        if self._filter_mode == FILTER_MODE_COUNTY:
            if COUNTY_ALL in self._counties:
                return True
            return any(str(value) in self._counties for value in condition.county_no)
        distance = self.distance_km(condition)
        return distance is not None and distance <= max(0.1, self._radius_km)

    def filter_conditions(self, conditions: list[RoadCondition]) -> list[RoadCondition]:
        """Apply geographic and exact/prefix road filters."""
        filtered = [
            condition
            for condition in conditions
            if self._in_scope(condition) and self._road_matches(condition)
        ]
        return sorted(
            filtered,
            key=lambda item: (
                -(item.condition_code or 0),
                self.distance_km(item)
                if self.distance_km(item) is not None
                else float("inf"),
                item.road_number_numeric or 0,
                item.condition_id,
            ),
        )

    async def _async_update_data(self) -> RoadConditionSnapshot:
        if not self._api_key:
            raise ConfigEntryAuthFailed("Missing API key")

        request = build_road_condition_request_xml(self._api_key)
        session = aiohttp_client.async_get_clientsession(self.hass)
        try:
            async with asyncio.timeout(20):
                async with session.post(
                    TRAFIKVERKET_DATACACHE_URL,
                    data=request.encode("utf-8"),
                    headers={
                        "Content-Type": "text/xml; charset=utf-8",
                        "User-Agent": get_user_agent(self.hass),
                    },
                ) as response:
                    response_text = await response.text()
                    if response.status in (401, 403):
                        raise TrafikinfoAuthenticationError(
                            f"Authentication failed: HTTP {response.status}"
                        )
                    if response.status != 200:
                        raise TrafikinfoAPIError(
                            "Trafikverket API returned "
                            f"HTTP {response.status}: {response_text[:300]}"
                        )
        except TrafikinfoAuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TrafikinfoError as err:
            raise UpdateFailed(str(err)) from err
        except TimeoutError:
            raise UpdateFailed(
                "Request timeout - Trafikverket API not responding"
            ) from None
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Connection error: {err}") from err
        except Exception as err:
            raise UpdateFailed(
                f"Unexpected error fetching Trafikverket road condition data: {err}"
            ) from err

        try:
            unfiltered = parse_road_condition_response(response_text)
        except TrafikinfoAuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TrafikinfoError as err:
            raise UpdateFailed(str(err)) from err

        conditions = self.filter_conditions(unfiltered.conditions)
        _LOGGER.debug(
            "Filtered road conditions: mode=%s counties=%s before=%s after=%s",
            self._filter_mode,
            sorted(self._counties),
            unfiltered.total_count,
            len(conditions),
        )
        return _snapshot(
            conditions,
            last_modified=unfiltered.last_modified,
            last_change_id=unfiltered.last_change_id,
        )
