"""Coordinator for Trafikinfo SE."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import math
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote
import xml.etree.ElementTree as ET

import aiohttp
import async_timeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
    CONF_SCAN_INTERVAL,
    CONF_SORT_LOCATION,
    CONF_SORT_MODE,
    COUNTY_ALL,
    DEFAULT_RADIUS_KM,
    DEFAULT_FILTER_MODE,
    DEFAULT_MAX_ITEMS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SORT_MODE,
    DOMAIN,
    FILTER_MODE_COORDINATE,
    FILTER_MODE_COUNTY,
    SITUATION_SCHEMA_VERSION,
    SORT_MODE_NEAREST,
    SORT_MODE_NEWEST,
    SORT_MODE_RELEVANCE,
    TRAFIKVERKET_DATACACHE_URL,
    TRAFIKVERKET_ICONS_BASE_URL,
    TRAFIKVERKET_ICON_V2_URL_PREFIX,
    ICON_CACHE_DIR,
    get_user_agent,
)

_LOGGER = logging.getLogger(__name__)

_WKT_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


class TrafikinfoError(Exception):
    """Base exception for Trafikinfo SE."""


class TrafikinfoConnectionError(TrafikinfoError):
    """Exception for connection errors."""


class TrafikinfoAuthenticationError(TrafikinfoError):
    """Exception for authentication errors."""


class TrafikinfoAPIError(TrafikinfoError):
    """Exception for API errors."""


class TrafikinfoParseError(TrafikinfoError):
    """Exception for XML parsing errors."""

def _file_nonempty(path: Path) -> bool:
    try:
        return path.exists() and path.stat().st_size > 0
    except OSError:
        return False


def _try_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)  # py3.8+: supported by HA
    except Exception:
        pass


def _looks_like_png(data: bytes) -> bool:
    return isinstance(data, (bytes, bytearray)) and data.startswith(b"\x89PNG\r\n\x1a\n")


def _looks_like_svg(data: bytes) -> bool:
    if not isinstance(data, (bytes, bytearray)):
        return False
    head = data[:300].lstrip()
    return head.startswith(b"<") and b"<svg" in head.lower()


@dataclass(frozen=True, slots=True)
class TrafikinfoEvent:
    """Flattened traffic event (one Deviation)."""

    situation_id: str | None
    deviation_id: str | None
    icon_id: str | None
    message_type: str | None
    message_type_value: str | None
    header: str | None
    message: str | None
    severity_code: int | None
    severity_text: str | None
    road_number: str | None
    road_name: str | None
    county_no: list[int]
    affected_direction: str | None
    affected_direction_value: str | None
    start_time: datetime | None
    end_time: datetime | None
    valid_until_further_notice: bool | None
    suspended: bool | None
    location_descriptor: str | None
    positional_description: str | None
    traffic_restriction_type: str | None
    temporary_limit: str | None
    number_of_lanes_restricted: int | None
    safety_related_message: bool | None
    weblink: str | None
    geometry_wgs84: str | None
    version_time: datetime | None
    publication_time: datetime | None
    modified_time: datetime | None

    def as_dict(self) -> dict[str, Any]:
        def _dt(v: datetime | None) -> str | None:
            return v.isoformat() if isinstance(v, datetime) else None

        icon_id = self.icon_id
        icon_url: str | None = None
        if icon_id:
            # Prefer the v2 icon dataset URL (matches what the Icon API returns in `Url`)
            icon_url = f"{TRAFIKVERKET_ICON_V2_URL_PREFIX}{quote(icon_id, safe='')}"

        return {
            "situation_id": self.situation_id,
            "deviation_id": self.deviation_id,
            "icon_id": icon_id,
            "icon_url": icon_url,
            "message_type": self.message_type,
            "message_type_value": self.message_type_value,
            "header": self.header,
            "message": self.message,
            "severity_code": self.severity_code,
            "severity_text": self.severity_text,
            "road_number": self.road_number,
            "road_name": self.road_name,
            "county_no": self.county_no,
            "affected_direction": self.affected_direction,
            "affected_direction_value": self.affected_direction_value,
            "start_time": _dt(self.start_time),
            "end_time": _dt(self.end_time),
            "valid_until_further_notice": self.valid_until_further_notice,
            "suspended": self.suspended,
            "location_descriptor": self.location_descriptor,
            "positional_description": self.positional_description,
            "traffic_restriction_type": self.traffic_restriction_type,
            "temporary_limit": self.temporary_limit,
            "number_of_lanes_restricted": self.number_of_lanes_restricted,
            "safety_related_message": self.safety_related_message,
            "weblink": self.weblink,
            "geometry_wgs84": self.geometry_wgs84,
            "version_time": _dt(self.version_time),
            "publication_time": _dt(self.publication_time),
            "modified_time": _dt(self.modified_time),
        }


@dataclass(frozen=True, slots=True)
class TrafikinfoData:
    """Coordinator payload."""

    events: list[TrafikinfoEvent]
    last_modified: datetime | None
    last_change_id: str | None
    sse_url: str | None


def _strip(s: str | None) -> str | None:
    if not isinstance(s, str):
        return None
    s2 = s.strip()
    return s2 if s2 else None


def _as_bool(v: str | None) -> bool | None:
    v = _strip(v)
    if v is None:
        return None
    if v.lower() in ("true", "1", "yes"):
        return True
    if v.lower() in ("false", "0", "no"):
        return False
    return None


def _as_int(v: str | None) -> int | None:
    v = _strip(v)
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _as_dt(v: str | None) -> datetime | None:
    v = _strip(v)
    if v is None:
        return None
    return dt_util.parse_datetime(v)


def _findtext(elem: ET.Element, path: str) -> str | None:
    # Namespace-agnostic element text lookup using local-name wildcards.
    # Example path: "./Id" or "./Deviation/MessageType"
    parts = [p for p in path.split("/") if p and p != "."]
    cur: ET.Element | None = elem
    for part in parts:
        if cur is None:
            return None
        if part == ".":
            continue
        cur = cur.find(f"./{{*}}{part}")
    if cur is None or cur.text is None:
        return None
    return cur.text


def _findall(elem: ET.Element, child_tag: str) -> list[ET.Element]:
    return list(elem.findall(f"./{{*}}{child_tag}"))


def _build_request_xml(api_key: str, *, limit: int) -> str:
    # Request schema: https://data.trafikverket.se/documentation/datacache/the-request
    # Data model: https://data.trafikverket.se/documentation/datacache/data-model?namespace=Road.TrafficInfo&collection=Situation
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<REQUEST>"
        f'<LOGIN authenticationkey="{api_key}" />'
        f'<QUERY objecttype="Situation" namespace="Road.TrafficInfo" schemaversion="{SITUATION_SCHEMA_VERSION}" limit="{int(limit)}">'
        "<FILTER>"
        "<AND>"
        '<EQ name="Deleted" value="false" />'
        "</AND>"
        "</FILTER>"
        # Pull full Deviation objects (simplifies mapping; still OK for v1).
        "<INCLUDE>CountryCode</INCLUDE>"
        "<INCLUDE>Deleted</INCLUDE>"
        "<INCLUDE>Id</INCLUDE>"
        "<INCLUDE>PublicationTime</INCLUDE>"
        "<INCLUDE>VersionTime</INCLUDE>"
        "<INCLUDE>ModifiedTime</INCLUDE>"
        "<INCLUDE>Deviation</INCLUDE>"
        "</QUERY>"
        "</REQUEST>"
    )


def _parse_response(xml_text: str) -> TrafikinfoData:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as err:
        raise TrafikinfoParseError(f"Invalid XML from Trafikverket: {err}") from err

    err_msg = root.findtext(".//{*}ERROR/{*}MESSAGE")
    if err_msg:
        if "authentication" in err_msg.lower() or "invalid key" in err_msg.lower():
            raise TrafikinfoAuthenticationError(f"Authentication failed: {err_msg.strip()}")
        raise TrafikinfoAPIError(f"Trafikverket API error: {err_msg.strip()}")

    last_modified_raw = root.find(".//{*}INFO/{*}LASTMODIFIED")
    last_modified: datetime | None = None
    if last_modified_raw is not None:
        dt_raw = last_modified_raw.attrib.get("datetime")
        last_modified = dt_util.parse_datetime(dt_raw) if dt_raw else None

    last_change_id = _strip(root.findtext(".//{*}INFO/{*}LASTCHANGEID"))
    sse_url = _strip(root.findtext(".//{*}INFO/{*}SSEURL"))

    now = dt_util.utcnow()
    events: list[TrafikinfoEvent] = []
    situation_count = 0
    deviation_count = 0

    for situation in root.findall(".//{*}Situation"):
        situation_count += 1
        deleted = _as_bool(_findtext(situation, "./Deleted"))
        if deleted is True:
            continue

        situation_id = _strip(_findtext(situation, "./Id"))
        pub_time = _as_dt(_findtext(situation, "./PublicationTime"))
        version_time = _as_dt(_findtext(situation, "./VersionTime"))
        modified_time = _as_dt(_findtext(situation, "./ModifiedTime"))

        deviations = _findall(situation, "Deviation")
        deviation_count += len(deviations)
        for dev in deviations:
            suspended = _as_bool(_findtext(dev, "./Suspended"))
            if suspended is True:
                continue

            end_time = _as_dt(_findtext(dev, "./EndTime"))
            if end_time is not None and end_time < now:
                continue

            start_time = _as_dt(_findtext(dev, "./StartTime"))

            county_no: list[int] = []
            for c in dev.findall("./{*}CountyNo"):
                val = _as_int(c.text)
                if val is not None:
                    county_no.append(val)

            # Geometry (prefer WGS84 if present)
            geom_wgs84 = _strip(dev.findtext(".//{*}Geometry//{*}WGS84"))

            events.append(
                TrafikinfoEvent(
                    situation_id=situation_id,
                    deviation_id=_strip(_findtext(dev, "./Id")),
                    icon_id=_strip(_findtext(dev, "./IconId")),
                    message_type=_strip(_findtext(dev, "./MessageType")),
                    message_type_value=_strip(_findtext(dev, "./MessageTypeValue")),
                    header=_strip(_findtext(dev, "./Header")),
                    message=_strip(_findtext(dev, "./Message")),
                    severity_code=_as_int(_findtext(dev, "./SeverityCode")),
                    severity_text=_strip(_findtext(dev, "./SeverityText")),
                    road_number=_strip(_findtext(dev, "./RoadNumber")),
                    road_name=_strip(_findtext(dev, "./RoadName")),
                    county_no=county_no,
                    affected_direction=_strip(_findtext(dev, "./AffectedDirection")),
                    affected_direction_value=_strip(_findtext(dev, "./AffectedDirectionValue")),
                    start_time=start_time,
                    end_time=end_time,
                    valid_until_further_notice=_as_bool(
                        _findtext(dev, "./ValidUntilFurtherNotice")
                    ),
                    suspended=suspended,
                    location_descriptor=_strip(_findtext(dev, "./LocationDescriptor")),
                    positional_description=_strip(_findtext(dev, "./PositionalDescription")),
                    traffic_restriction_type=_strip(
                        _findtext(dev, "./TrafficRestrictionType")
                    ),
                    temporary_limit=_strip(_findtext(dev, "./TemporaryLimit")),
                    number_of_lanes_restricted=_as_int(
                        _findtext(dev, "./NumberOfLanesRestricted")
                    ),
                    safety_related_message=_as_bool(
                        _findtext(dev, "./SafetyRelatedMessage")
                    ),
                    weblink=_strip(_findtext(dev, "./WebLink")),
                    geometry_wgs84=geom_wgs84,
                    version_time=version_time,
                    publication_time=pub_time,
                    modified_time=modified_time,
                )
            )

    _LOGGER.debug(
        "Parsed Trafikverket response: situations=%s deviations=%s events_active=%s",
        situation_count,
        deviation_count,
        len(events),
    )

    # A stable-ish order: newest first by publication_time, then id.
    def _sort_key(e: TrafikinfoEvent):
        return (
            e.publication_time or datetime.min.replace(tzinfo=dt_util.UTC),
            e.situation_id or "",
            e.deviation_id or "",
        )

    events.sort(key=_sort_key, reverse=True)

    return TrafikinfoData(
        events=events,
        last_modified=last_modified,
        last_change_id=last_change_id,
        sse_url=sse_url,
    )


class TrafikinfoCoordinator(DataUpdateCoordinator[TrafikinfoData]):
    """Fetch and parse Trafikverket Situation data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry = entry
        self._api_key = str(entry.data.get(CONF_API_KEY, "")).strip()
        self._max_items = int(
            entry.options.get(CONF_MAX_ITEMS, entry.data.get(CONF_MAX_ITEMS, DEFAULT_MAX_ITEMS))
        )
        self._filter_roads: list[str] = []
        raw_roads = entry.options.get(CONF_FILTER_ROADS, entry.data.get(CONF_FILTER_ROADS, []))
        if isinstance(raw_roads, str):
            parts: list[str] = []
            for chunk in raw_roads.split(";"):
                parts.extend(chunk.split(","))
            raw_roads = parts
        if isinstance(raw_roads, list):
            self._filter_roads = [str(x).strip() for x in raw_roads if str(x).strip()]
        self._sort_mode = str(
            entry.options.get(CONF_SORT_MODE, entry.data.get(CONF_SORT_MODE, DEFAULT_SORT_MODE))
        )
        if self._sort_mode not in (SORT_MODE_RELEVANCE, SORT_MODE_NEAREST, SORT_MODE_NEWEST):
            self._sort_mode = DEFAULT_SORT_MODE
        self._filter_mode = str(
            entry.options.get(CONF_FILTER_MODE, entry.data.get(CONF_FILTER_MODE, DEFAULT_FILTER_MODE))
        )
        if self._filter_mode not in (FILTER_MODE_COORDINATE, FILTER_MODE_COUNTY):
            # Backward compatibility for earlier values (e.g. "sweden") or unknown values.
            self._filter_mode = FILTER_MODE_COUNTY
        self._counties: set[str] = set()
        raw_counties = entry.options.get(CONF_COUNTIES, entry.data.get(CONF_COUNTIES, []))
        if isinstance(raw_counties, list):
            self._counties = {str(x) for x in raw_counties if str(x).strip()}
        # If mode is county but counties is empty, default to Sweden-wide.
        if self._filter_mode == FILTER_MODE_COUNTY and not self._counties:
            self._counties = {COUNTY_ALL}
        self._latitude = float(
            entry.options.get(CONF_LATITUDE, entry.data.get(CONF_LATITUDE, hass.config.latitude))
        )
        self._longitude = float(
            entry.options.get(CONF_LONGITUDE, entry.data.get(CONF_LONGITUDE, hass.config.longitude))
        )
        # Sorting reference point:
        # - Coordinate mode: uses the configured center (lat/lon)
        # - County mode: defaults to HA home location, but can be overridden via sort_location
        self._sort_latitude = float(hass.config.latitude)
        self._sort_longitude = float(hass.config.longitude)
        if self._filter_mode == FILTER_MODE_COORDINATE:
            self._sort_latitude = float(self._latitude)
            self._sort_longitude = float(self._longitude)
        else:
            sort_loc = entry.options.get(CONF_SORT_LOCATION, entry.data.get(CONF_SORT_LOCATION))
            if isinstance(sort_loc, dict):
                try:
                    self._sort_latitude = float(sort_loc.get("latitude", hass.config.latitude))
                    self._sort_longitude = float(sort_loc.get("longitude", hass.config.longitude))
                except (TypeError, ValueError):
                    self._sort_latitude = float(hass.config.latitude)
                    self._sort_longitude = float(hass.config.longitude)
        self._radius_km = float(
            entry.options.get(CONF_RADIUS_KM, entry.data.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM))
        )
        self._icon_local_urls: dict[str, str] = {}

        scan_minutes = int(
            entry.options.get(
                CONF_SCAN_INTERVAL,
                entry.data.get(CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds() / 60)),
            )
        )
        update_interval = timedelta(minutes=max(1, scan_minutes))

        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def filter_mode(self) -> str:
        return self._filter_mode

    @property
    def counties(self) -> list[str]:
        # Stable ordering for UI/attributes
        return sorted(self._counties)

    @property
    def max_items(self) -> int:
        return self._max_items

    @property
    def filter_roads(self) -> list[str]:
        return list(self._filter_roads)

    @property
    def sort_mode(self) -> str:
        return self._sort_mode

    @property
    def sort_latitude(self) -> float:
        return self._sort_latitude

    @property
    def sort_longitude(self) -> float:
        return self._sort_longitude

    @property
    def latitude(self) -> float:
        return self._latitude

    @property
    def longitude(self) -> float:
        return self._longitude

    @property
    def radius_km(self) -> float:
        return self._radius_km

    def apply_options(self) -> None:
        """Apply updated options from the config entry."""
        raw_roads = self._entry.options.get(CONF_FILTER_ROADS, self._entry.data.get(CONF_FILTER_ROADS, []))
        if isinstance(raw_roads, str):
            parts: list[str] = []
            for chunk in raw_roads.split(";"):
                parts.extend(chunk.split(","))
            raw_roads = parts
        if isinstance(raw_roads, list):
            self._filter_roads = [str(x).strip() for x in raw_roads if str(x).strip()]
        else:
            self._filter_roads = []
        self._sort_mode = str(
            self._entry.options.get(CONF_SORT_MODE, self._entry.data.get(CONF_SORT_MODE, DEFAULT_SORT_MODE))
        )
        if self._sort_mode not in (SORT_MODE_RELEVANCE, SORT_MODE_NEAREST, SORT_MODE_NEWEST):
            self._sort_mode = DEFAULT_SORT_MODE
        self._filter_mode = str(
            self._entry.options.get(
                CONF_FILTER_MODE,
                self._entry.data.get(CONF_FILTER_MODE, DEFAULT_FILTER_MODE),
            )
        )
        if self._filter_mode not in (FILTER_MODE_COORDINATE, FILTER_MODE_COUNTY):
            self._filter_mode = FILTER_MODE_COUNTY
        self._counties = set()
        raw_counties = self._entry.options.get(CONF_COUNTIES, self._entry.data.get(CONF_COUNTIES, []))
        if isinstance(raw_counties, list):
            self._counties = {str(x) for x in raw_counties if str(x).strip()}
        if self._filter_mode == FILTER_MODE_COUNTY and not self._counties:
            self._counties = {COUNTY_ALL}

        scan_minutes = int(
            self._entry.options.get(
                CONF_SCAN_INTERVAL,
                self._entry.data.get(
                    CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds() / 60)
                ),
            )
        )
        self.update_interval = timedelta(minutes=max(1, scan_minutes))
        self._max_items = int(
            self._entry.options.get(
                CONF_MAX_ITEMS, self._entry.data.get(CONF_MAX_ITEMS, DEFAULT_MAX_ITEMS)
            )
        )
        self._latitude = float(
            self._entry.options.get(
                CONF_LATITUDE, self._entry.data.get(CONF_LATITUDE, self.hass.config.latitude)
            )
        )
        self._longitude = float(
            self._entry.options.get(
                CONF_LONGITUDE,
                self._entry.data.get(CONF_LONGITUDE, self.hass.config.longitude),
            )
        )
        self._radius_km = float(
            self._entry.options.get(
                CONF_RADIUS_KM, self._entry.data.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM)
            )
        )
        # Recompute sorting reference point
        if self._filter_mode == FILTER_MODE_COORDINATE:
            self._sort_latitude = float(self._latitude)
            self._sort_longitude = float(self._longitude)
        else:
            sort_loc = self._entry.options.get(CONF_SORT_LOCATION, self._entry.data.get(CONF_SORT_LOCATION))
            if isinstance(sort_loc, dict):
                try:
                    self._sort_latitude = float(sort_loc.get("latitude", self.hass.config.latitude))
                    self._sort_longitude = float(sort_loc.get("longitude", self.hass.config.longitude))
                except (TypeError, ValueError):
                    self._sort_latitude = float(self.hass.config.latitude)
                    self._sort_longitude = float(self.hass.config.longitude)
            else:
                self._sort_latitude = float(self.hass.config.latitude)
                self._sort_longitude = float(self.hass.config.longitude)

    def _is_important_without_geo(self, event: TrafikinfoEvent) -> bool:
        if event.safety_related_message is True:
            return True
        if event.message_type == "Viktig trafikinformation":
            return True
        return False

    def _normalize_road_filter_token(self, value: str) -> str:
        s = (value or "").strip().lower()
        if not s:
            return ""
        # Allow user-friendly inputs like "Väg 163" / "Road 163" by stripping the prefix.
        s = re.sub(r"^(väg|vag|road)\s+", "", s, flags=re.IGNORECASE)
        # Normalize whitespace
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _road_filter_match(self, event: TrafikinfoEvent, tokens: list[str]) -> bool:
        if not tokens:
            return True
        road_text = f"{event.road_name or ''} {event.road_number or ''}".lower()
        road_no = (event.road_number or "").strip().lower()
        for t in tokens:
            if not t:
                continue
            if road_no and t == road_no:
                return True
            if t in road_text:
                return True
        return False

    def _apply_road_filter(self, events: list[TrafikinfoEvent]) -> list[TrafikinfoEvent]:
        """Apply road filter, but never drop important safety/national messages."""
        if not self._filter_roads:
            return events
        tokens = [self._normalize_road_filter_token(x) for x in self._filter_roads]
        tokens = [t for t in tokens if t]
        if not tokens:
            return events
        out: list[TrafikinfoEvent] = []
        for e in events:
            if self._is_important_without_geo(e):
                out.append(e)
                continue
            if self._road_filter_match(e, tokens):
                out.append(e)
        return out

    def event_distance_km(self, event: TrafikinfoEvent) -> float | None:
        """Compute min distance (km) from sorting reference to event geometry."""
        if not event.geometry_wgs84:
            return None
        pts = self._wkt_points(event.geometry_wgs84)
        if not pts:
            return None
        center_lon = float(self._sort_longitude)
        center_lat = float(self._sort_latitude)
        best: float | None = None
        for lon, lat in pts[:200]:  # cap work for huge geometries
            d = self._haversine_km(center_lon, center_lat, lon, lat)
            if best is None or d < best:
                best = d
        return best

    def sort_events(self, events: list[TrafikinfoEvent]) -> list[TrafikinfoEvent]:
        """Sort events according to configured sort_mode."""
        if not events:
            return []

        def _pub_ts(e: TrafikinfoEvent) -> float:
            pub = e.publication_time
            if not isinstance(pub, datetime):
                return 0.0
            try:
                return float(pub.timestamp())
            except Exception:
                return 0.0

        if self._sort_mode == SORT_MODE_NEWEST:
            # Already newest-first globally, but filter may disturb ordering in future;
            # make it explicit and stable.
            def _k_newest(e: TrafikinfoEvent):
                return (
                    e.publication_time or datetime.min.replace(tzinfo=dt_util.UTC),
                    e.situation_id or "",
                    e.deviation_id or "",
                )

            return sorted(events, key=_k_newest, reverse=True)

        # Nearest / relevance need distances. Cache per call (avoid recompute per key element).
        dist_cache: dict[tuple[str | None, str | None], float | None] = {}

        def _dist(e: TrafikinfoEvent) -> float | None:
            key = (e.situation_id, e.deviation_id)
            if key in dist_cache:
                return dist_cache[key]
            dist_cache[key] = self.event_distance_km(e)
            return dist_cache[key]

        def _k_nearest(e: TrafikinfoEvent):
            d = _dist(e)
            missing = 1 if d is None else 0  # known distances first
            dval = float(d) if d is not None else float("inf")
            # Newest first as tie-breaker
            return (missing, dval, -_pub_ts(e), e.situation_id or "", e.deviation_id or "")

        if self._sort_mode == SORT_MODE_NEAREST:
            return sorted(events, key=_k_nearest, reverse=False)

        # Default: relevance (important first, then nearest, then newest)
        def _k_relevance(e: TrafikinfoEvent):
            important = 0 if self._is_important_without_geo(e) else 1
            d = _dist(e)
            missing = 1 if d is None else 0
            dval = float(d) if d is not None else float("inf")
            # Newest first within same bucket:
            return (important, missing, dval, -_pub_ts(e), e.situation_id or "", e.deviation_id or "")

        return sorted(events, key=_k_relevance, reverse=False)

    def _in_counties(self, event: TrafikinfoEvent) -> bool:
        if COUNTY_ALL in self._counties:
            return True
        if not self._counties:
            return False
        if not event.county_no:
            return self._is_important_without_geo(event)
        for c in event.county_no:
            if str(c) in self._counties:
                return True
        return False

    def _include_event(self, event: TrafikinfoEvent) -> bool:
        if self._filter_mode == FILTER_MODE_COUNTY:
            return self._in_counties(event)
        return self._in_radius(event)

    def get_local_icon_url(self, icon_id: str | None) -> str | None:
        if not icon_id:
            return None
        return self._icon_local_urls.get(icon_id)

    def get_remote_icon_url(self, icon_id: str | None) -> str | None:
        """Return a remote icon URL that is likely to work for the given IconId."""
        if not icon_id:
            return None
        return f"{TRAFIKVERKET_ICON_V2_URL_PREFIX}{quote(icon_id, safe='')}"

    def _icon_cache_dir(self) -> Path:
        # /config/www maps to /local in HA.
        return Path(self.hass.config.path("www")) / ICON_CACHE_DIR

    def _safe_icon_filename(self, icon_id: str, ext: str) -> str:
        # Keep stable and filesystem-safe, avoid path traversal.
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in icon_id)
        if not safe:
            safe = "icon"
        return f"{safe}.{ext}"

    async def _async_write_file(self, path: Path, content: bytes) -> None:
        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(content)
            tmp.replace(path)

        await self.hass.async_add_executor_job(_write)

    async def _ensure_icon_cached(self, icon_id: str) -> None:
        if icon_id in self._icon_local_urls:
            return

        cache_dir = self._icon_cache_dir()
        # Default to png; we may switch to svg if response indicates it.
        png_name = self._safe_icon_filename(icon_id, "png")
        svg_name = self._safe_icon_filename(icon_id, "svg")
        png_path = cache_dir / png_name
        svg_path = cache_dir / svg_name

        if _file_nonempty(png_path):
            self._icon_local_urls[icon_id] = f"/local/{ICON_CACHE_DIR}/{png_name}"
            return
        if _file_nonempty(svg_path):
            self._icon_local_urls[icon_id] = f"/local/{ICON_CACHE_DIR}/{svg_name}"
            return
        # If we have empty/partial files from earlier runs, delete and re-download.
        if png_path.exists() and not _file_nonempty(png_path):
            await self.hass.async_add_executor_job(_try_unlink, png_path)
        if svg_path.exists() and not _file_nonempty(svg_path):
            await self.hass.async_add_executor_job(_try_unlink, svg_path)

        session = aiohttp_client.async_get_clientsession(self.hass)

        # Prefer v2 icon URL (matches Icon dataset Url field).
        url_v2 = self.get_remote_icon_url(icon_id)
        # Fallback to v1 typed URL.
        url_v1 = f"{TRAFIKVERKET_ICONS_BASE_URL}/{quote(icon_id, safe='')}?type=png32x32"

        for url in (url_v2, url_v1):
            if not url:
                continue
            try:
                async with async_timeout.timeout(15):
                    async with session.get(
                        url,
                        headers={"User-Agent": get_user_agent(self.hass)},
                    ) as resp:
                        if resp.status != 200:
                            continue
                        content = await resp.read()
                        ctype = (resp.headers.get("Content-Type") or "").lower()
                        # Only cache if the payload looks like an actual image.
                        # Some endpoints can return JSON error payloads with 200/4xx;
                        # don't write those to disk as .png/.svg.
                        if ("svg" in ctype) or _looks_like_svg(content):
                            if not _looks_like_svg(content):
                                continue
                            await self._async_write_file(svg_path, content)
                            self._icon_local_urls[icon_id] = f"/local/{ICON_CACHE_DIR}/{svg_name}"
                        elif ("png" in ctype) or _looks_like_png(content):
                            if not _looks_like_png(content):
                                continue
                            await self._async_write_file(png_path, content)
                            self._icon_local_urls[icon_id] = f"/local/{ICON_CACHE_DIR}/{png_name}"
                        else:
                            continue
                        return
            except Exception:
                continue

    async def _ensure_icons_cached(self, icon_ids: list[str]) -> None:
        # Cache a limited number to avoid hammering the endpoint.
        unique: list[str] = []
        seen: set[str] = set()
        for i in icon_ids:
            if i in seen:
                continue
            seen.add(i)
            unique.append(i)
            if len(unique) >= 50:
                break
        for icon_id in unique:
            await self._ensure_icon_cached(icon_id)

    async def _ensure_category_icons_cached(self) -> None:
        # Stable icons we want available even if current events have no IconId.
        for icon_id in (
            "roadAccident",
            "trafficMessage",
            "emergencyInformation",
            "trafficMessagePlanned",
        ):
            await self._ensure_icon_cached(icon_id)

    async def _cache_icons_background(self, icon_ids: list[str]) -> None:
        """Cache icons in background task to not block coordinator updates."""
        try:
            await self._ensure_icons_cached(icon_ids)
            await self._ensure_category_icons_cached()
        except Exception as err:
            _LOGGER.debug("Icon caching failed: %s", err)

    def _wkt_points(self, wkt: str | None) -> list[tuple[float, float]]:
        """Extract lon/lat points from common WKT shapes (POINT/LINESTRING/etc)."""
        if not isinstance(wkt, str):
            return []
        s = wkt.strip()
        if not s:
            return []

        header = s.split("(", 1)[0].upper()
        # WKT can be "POINT Z (...)" / "LINESTRING Z (...)" etc.
        dim = 3 if " Z" in header or header.endswith("Z") else 2

        nums = _WKT_NUMBER_RE.findall(s)
        # WKT is "X Y" (lon lat) pairs; Z may appear. We only use lon/lat.
        if len(nums) < 2:
            return []

        floats: list[float] = []
        for n in nums:
            try:
                floats.append(float(n))
            except ValueError:
                continue

        pts: list[tuple[float, float]] = []
        step = 3 if dim == 3 else 2
        i = 0
        while i + 1 < len(floats):
            lon = floats[i]
            lat = floats[i + 1]
            pts.append((lon, lat))
            i += step
        return pts

    def _haversine_km(self, lon1: float, lat1: float, lon2: float, lat2: float) -> float:
        r = 6371.0
        p1 = math.radians(lat1)
        p2 = math.radians(lat2)
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
        return 2 * r * math.asin(math.sqrt(a))

    def _in_radius(self, event: TrafikinfoEvent) -> bool:
        # Include important unlocated messages (often national) to avoid missing safety info.
        if not event.geometry_wgs84:
            return self._is_important_without_geo(event)

        pts = self._wkt_points(event.geometry_wgs84)
        if not pts:
            return False

        # Compute minimum distance to any point in the geometry.
        center_lon = float(self._longitude)
        center_lat = float(self._latitude)
        radius = max(0.1, float(self._radius_km))
        for lon, lat in pts[:200]:  # cap work for huge geometries
            if self._haversine_km(center_lon, center_lat, lon, lat) <= radius:
                return True
        return False

    async def _async_update_data(self) -> TrafikinfoData:
        if not self._api_key:
            raise TrafikinfoAuthenticationError("Missing API key")

        session = aiohttp_client.async_get_clientsession(self.hass)
        xml_request = _build_request_xml(self._api_key, limit=5000)

        try:
            async with async_timeout.timeout(20):
                async with session.post(
                    TRAFIKVERKET_DATACACHE_URL,
                    data=xml_request.encode("utf-8"),
                    headers={
                        "Content-Type": "text/xml; charset=utf-8",
                        "User-Agent": get_user_agent(self.hass),
                    },
                ) as resp:
                    text = await resp.text()
                    if resp.status in (401, 403):
                        raise TrafikinfoAuthenticationError(
                            f"Authentication failed: HTTP {resp.status}"
                        )
                    if resp.status != 200:
                        raise TrafikinfoAPIError(
                            f"Trafikverket API returned HTTP {resp.status}: {text[:300]}"
                        )
        except TrafikinfoError as err:
            raise UpdateFailed(str(err)) from err
        except asyncio.TimeoutError:
            raise UpdateFailed("Request timeout - Trafikverket API not responding") from None
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Connection error: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error fetching Trafikverket data: {err}") from err

        try:
            data = _parse_response(text)
        except TrafikinfoError as err:
            raise UpdateFailed(str(err)) from err
        filtered = [e for e in data.events if self._include_event(e)]
        filtered = self._apply_road_filter(filtered)
        # Best-effort local icon caching for picture cards (run in background to not block)
        icon_ids = [e.icon_id for e in filtered if e.icon_id]
        self.hass.async_create_background_task(
            self._cache_icons_background([i for i in icon_ids if isinstance(i, str)]),
            f"{DOMAIN}_icon_cache",
        )
        _LOGGER.debug(
            "Filter: mode=%s center=(%.5f,%.5f) radius_km=%.1f counties=%s events_before=%s events_after=%s",
            self._filter_mode,
            self._latitude,
            self._longitude,
            self._radius_km,
            sorted(self._counties),
            len(data.events),
            len(filtered),
        )
        return TrafikinfoData(
            events=filtered,
            last_modified=data.last_modified,
            last_change_id=data.last_change_id,
            sse_url=data.sse_url,
        )


