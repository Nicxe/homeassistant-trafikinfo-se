"""TrafficFlow support for Trafikinfo SE."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from xml.sax.saxutils import quoteattr

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_API_KEY,
    CONF_TRAFFIC_FLOW_SITE_IDS,
    CONF_TRAFFIC_FLOW_SITE_LABEL,
    CONF_TRAFFIC_FLOW_SITE_LATITUDE,
    CONF_TRAFFIC_FLOW_SITE_LONGITUDE,
    DEFAULT_TRAFFIC_FLOW_SCAN_INTERVAL,
    DOMAIN,
    TRAFFIC_FLOW_SCHEMA_VERSION,
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

TRAFFIC_FLOW_QUALITY_NO_DATA = "no_data"
TRAFFIC_FLOW_QUALITY_GOOD = "good"
TRAFFIC_FLOW_QUALITY_DEGRADED = "degraded"
TRAFFIC_FLOW_QUALITY_BAD = "bad"
TRAFFIC_FLOW_QUALITY_STALE = "stale"
TRAFFIC_FLOW_QUALITY_UNKNOWN = "unknown"

TRAFFIC_FLOW_QUALITY_STATES = [
    TRAFFIC_FLOW_QUALITY_NO_DATA,
    TRAFFIC_FLOW_QUALITY_GOOD,
    TRAFFIC_FLOW_QUALITY_DEGRADED,
    TRAFFIC_FLOW_QUALITY_BAD,
    TRAFFIC_FLOW_QUALITY_STALE,
    TRAFFIC_FLOW_QUALITY_UNKNOWN,
]

TRAFFIC_FLOW_STALE_AFTER = timedelta(minutes=5)
TRAFFIC_FLOW_SITE_CLUSTER_METERS = 15.0
TRAFFIC_FLOW_DISCOVERY_LIMIT = 5000
TRAFFIC_FLOW_NEARBY_LIMIT = 500

_QUALITY_PRIORITY = {
    TRAFFIC_FLOW_QUALITY_GOOD: 0,
    TRAFFIC_FLOW_QUALITY_UNKNOWN: 1,
    TRAFFIC_FLOW_QUALITY_DEGRADED: 2,
    TRAFFIC_FLOW_QUALITY_STALE: 3,
    TRAFFIC_FLOW_QUALITY_BAD: 4,
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


def _as_float(value: str | None) -> float | None:
    value = _strip(value)
    if value is None:
        return None
    try:
        return float(value)
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
    return dt_util.parse_datetime(value) if value is not None else None


def _wgs84_point(wkt: str | None) -> tuple[float, float] | None:
    if not isinstance(wkt, str) or not wkt.strip():
        return None
    values = [float(value) for value in _WKT_NUMBER_RE.findall(wkt)]
    if len(values) < 2:
        return None
    return values[0], values[1]


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


@dataclass(frozen=True, slots=True)
class TrafficFlowMeasurement:
    """One current Trafikverket traffic-flow detector measurement."""

    site_id: str
    average_vehicle_speed: float | None
    county_no: int | None
    data_quality: str | None
    deleted: bool | None
    measurement_period_s: int | None
    measurement_side: str | None
    measurement_time: datetime | None
    modified_time: datetime | None
    region_id: int | None
    specific_lane: str | None
    vehicle_flow_rate: int | None
    vehicle_type: str | None
    geometry_wgs84: str | None

    @property
    def point(self) -> tuple[float, float] | None:
        """Return the detector's WGS84 longitude and latitude."""
        return _wgs84_point(self.geometry_wgs84)

    def effective_quality(self, now: datetime) -> str:
        """Return quality including freshness validation."""
        quality = str(self.data_quality or "").strip().lower()
        if quality == TRAFFIC_FLOW_QUALITY_BAD:
            return TRAFFIC_FLOW_QUALITY_BAD
        if self.measurement_time is None:
            return TRAFFIC_FLOW_QUALITY_UNKNOWN
        if now - self.measurement_time > TRAFFIC_FLOW_STALE_AFTER:
            return TRAFFIC_FLOW_QUALITY_STALE
        if quality == TRAFFIC_FLOW_QUALITY_GOOD:
            return TRAFFIC_FLOW_QUALITY_GOOD
        if quality == TRAFFIC_FLOW_QUALITY_DEGRADED:
            return TRAFFIC_FLOW_QUALITY_DEGRADED
        return TRAFFIC_FLOW_QUALITY_UNKNOWN

    def as_dict(self, *, now: datetime) -> dict[str, Any]:
        """Return stable Home Assistant state attributes."""

        def _dt(value: datetime | None) -> str | None:
            return value.isoformat() if value is not None else None

        point = self.point
        return {
            "site_id": self.site_id,
            "average_vehicle_speed_kmh": self.average_vehicle_speed,
            "county_no": self.county_no,
            "data_quality": self.data_quality,
            "effective_quality": self.effective_quality(now),
            "measurement_period_s": self.measurement_period_s,
            "measurement_side": self.measurement_side,
            "measurement_time": _dt(self.measurement_time),
            "modified_time": _dt(self.modified_time),
            "region_id": self.region_id,
            "specific_lane": self.specific_lane,
            "vehicle_flow_rate": self.vehicle_flow_rate,
            "vehicle_type": self.vehicle_type,
            "geometry_wgs84": self.geometry_wgs84,
            "longitude": point[0] if point is not None else None,
            "latitude": point[1] if point is not None else None,
        }


@dataclass(frozen=True, slots=True)
class TrafficFlowSnapshot:
    """Aggregated current state for one selected traffic-flow site."""

    measurements: list[TrafficFlowMeasurement]
    total_flow_rate: int | None
    weighted_average_speed: float | None
    data_quality: str
    measurement_time: datetime | None
    data_age_minutes: float | None
    valid_measurement_count: int
    total_measurement_count: int
    last_modified: datetime | None
    last_change_id: str | None


def traffic_flow_snapshot(
    measurements: list[TrafficFlowMeasurement],
    *,
    now: datetime | None = None,
    last_modified: datetime | None = None,
    last_change_id: str | None = None,
) -> TrafficFlowSnapshot:
    """Aggregate lane detectors without treating bad or stale data as valid."""
    current_time = now or dt_util.utcnow()
    qualities = [item.effective_quality(current_time) for item in measurements]
    if qualities:
        quality = max(qualities, key=lambda value: _QUALITY_PRIORITY[value])
    else:
        quality = TRAFFIC_FLOW_QUALITY_NO_DATA

    usable = [
        item
        for item in measurements
        if item.effective_quality(current_time)
        in (TRAFFIC_FLOW_QUALITY_GOOD, TRAFFIC_FLOW_QUALITY_DEGRADED)
    ]
    flow_values = [
        item.vehicle_flow_rate
        for item in usable
        if item.vehicle_flow_rate is not None and item.vehicle_flow_rate >= 0
    ]
    total_flow = sum(flow_values) if flow_values else None

    weighted_speed_values = [
        (item.average_vehicle_speed, item.vehicle_flow_rate)
        for item in usable
        if item.average_vehicle_speed is not None
        and item.vehicle_flow_rate is not None
        and item.vehicle_flow_rate > 0
    ]
    total_weight = sum(flow for _, flow in weighted_speed_values)
    weighted_speed = (
        sum(speed * flow for speed, flow in weighted_speed_values) / total_weight
        if total_weight > 0
        else None
    )

    times = [item.measurement_time for item in measurements if item.measurement_time]
    measurement_time = max(times) if times else None
    age_minutes = None
    if measurement_time is not None:
        age_minutes = max(0.0, (current_time - measurement_time).total_seconds() / 60.0)

    modified_times = [item.modified_time for item in measurements if item.modified_time]
    if last_modified is None and modified_times:
        last_modified = max(modified_times)

    return TrafficFlowSnapshot(
        measurements=measurements,
        total_flow_rate=total_flow,
        weighted_average_speed=round(weighted_speed, 2)
        if weighted_speed is not None
        else None,
        data_quality=quality,
        measurement_time=measurement_time,
        data_age_minutes=round(age_minutes, 2) if age_minutes is not None else None,
        valid_measurement_count=len(usable),
        total_measurement_count=len(measurements),
        last_modified=last_modified,
        last_change_id=last_change_id,
    )


@dataclass(frozen=True, slots=True)
class TrafficFlowSite:
    """A user-selectable group of nearby lane detectors."""

    site_ids: tuple[str, ...]
    latitude: float
    longitude: float
    county_no: int | None
    measurement_side: str | None
    lanes: tuple[str, ...]
    distance_km: float
    snapshot: TrafficFlowSnapshot

    @property
    def site_key(self) -> str:
        """Return a stable selector value for the discovered detector group."""
        return "-".join(self.site_ids)


_TRAFFIC_FLOW_FIELDS = (
    "AverageVehicleSpeed",
    "CountyNo",
    "DataQuality",
    "Deleted",
    "Geometry",
    "MeasurementOrCalculationPeriod",
    "MeasurementSide",
    "MeasurementTime",
    "ModifiedTime",
    "RegionId",
    "SiteId",
    "SpecificLane",
    "VehicleFlowRate",
    "VehicleType",
)


def _include_xml() -> str:
    return "".join(f"<INCLUDE>{field}</INCLUDE>" for field in _TRAFFIC_FLOW_FIELDS)


def build_traffic_flow_discovery_request_xml(
    api_key: str,
    *,
    latitude: float,
    longitude: float,
    radius_km: float,
    county_no: str | None = None,
) -> str:
    """Build a server-filtered request for selectable traffic-flow sites."""
    filters = [
        '<EQ name="Deleted" value="false" />',
        '<EQ name="VehicleType" value="anyVehicle" />',
    ]
    if county_no is not None:
        filters.append(f'<EQ name="CountyNo" value={quoteattr(str(county_no))} />')
        limit = TRAFFIC_FLOW_DISCOVERY_LIMIT
    else:
        filters.append(
            '<NEAR name="Geometry.WGS84" '
            f"value={quoteattr(f'{longitude:.7f} {latitude:.7f}')} "
            'mindistance="0" '
            f"maxdistance={quoteattr(str(max(1000, round(radius_km * 1000))))} />"
        )
        limit = TRAFFIC_FLOW_NEARBY_LIMIT

    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<REQUEST>"
        f"<LOGIN authenticationkey={quoteattr(api_key)} />"
        f'<QUERY objecttype="TrafficFlow" namespace="Road.TrafficInfo" '
        f'schemaversion="{TRAFFIC_FLOW_SCHEMA_VERSION}" limit="{limit}">'
        f"<FILTER><AND>{''.join(filters)}</AND></FILTER>"
        f"{_include_xml()}"
        "</QUERY>"
        "</REQUEST>"
    )


def build_traffic_flow_site_request_xml(
    api_key: str, *, site_ids: list[str] | tuple[str, ...]
) -> str:
    """Build a minimal recurring request for one selected detector group."""
    normalized_ids = sorted(
        {str(site_id).strip() for site_id in site_ids if str(site_id).strip()},
        key=lambda value: (
            not value.isdigit(),
            int(value) if value.isdigit() else value,
        ),
    )
    site_values = ", ".join(normalized_ids)
    limit = max(10, len(normalized_ids) * 2)
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<REQUEST>"
        f"<LOGIN authenticationkey={quoteattr(api_key)} />"
        f'<QUERY objecttype="TrafficFlow" namespace="Road.TrafficInfo" '
        f'schemaversion="{TRAFFIC_FLOW_SCHEMA_VERSION}" limit="{limit}">'
        "<FILTER><AND>"
        '<EQ name="Deleted" value="false" />'
        '<EQ name="VehicleType" value="anyVehicle" />'
        f'<IN name="SiteId" value={quoteattr(site_values)} />'
        "</AND></FILTER>"
        f"{_include_xml()}"
        "</QUERY>"
        "</REQUEST>"
    )


def parse_traffic_flow_response(
    xml_text: str, *, now: datetime | None = None
) -> TrafficFlowSnapshot:
    """Parse current detector records and API metadata."""
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

    measurements: list[TrafficFlowMeasurement] = []
    for element in root.findall(".//{*}TrafficFlow"):
        if _as_bool(element.findtext("./{*}Deleted")) is True:
            continue
        site_id = _strip(element.findtext("./{*}SiteId"))
        if site_id is None:
            continue
        measurements.append(
            TrafficFlowMeasurement(
                site_id=site_id,
                average_vehicle_speed=_as_float(
                    element.findtext("./{*}AverageVehicleSpeed")
                ),
                county_no=_as_int(element.findtext("./{*}CountyNo")),
                data_quality=_strip(element.findtext("./{*}DataQuality")),
                deleted=_as_bool(element.findtext("./{*}Deleted")),
                measurement_period_s=_as_int(
                    element.findtext("./{*}MeasurementOrCalculationPeriod")
                ),
                measurement_side=_strip(element.findtext("./{*}MeasurementSide")),
                measurement_time=_as_dt(element.findtext("./{*}MeasurementTime")),
                modified_time=_as_dt(element.findtext("./{*}ModifiedTime")),
                region_id=_as_int(element.findtext("./{*}RegionId")),
                specific_lane=_strip(element.findtext("./{*}SpecificLane")),
                vehicle_flow_rate=_as_int(element.findtext("./{*}VehicleFlowRate")),
                vehicle_type=_strip(element.findtext("./{*}VehicleType")),
                geometry_wgs84=_strip(element.findtext("./{*}Geometry/{*}WGS84")),
            )
        )

    measurements.sort(
        key=lambda item: (
            item.specific_lane or "",
            not item.site_id.isdigit(),
            int(item.site_id) if item.site_id.isdigit() else item.site_id,
        )
    )
    last_modified_element = root.find(".//{*}INFO/{*}LASTMODIFIED")
    last_modified = None
    if last_modified_element is not None:
        last_modified = _as_dt(last_modified_element.attrib.get("datetime"))
    return traffic_flow_snapshot(
        measurements,
        now=now,
        last_modified=last_modified,
        last_change_id=_strip(root.findtext(".//{*}INFO/{*}LASTCHANGEID")),
    )


def group_traffic_flow_sites(
    measurements: list[TrafficFlowMeasurement],
    *,
    origin_latitude: float,
    origin_longitude: float,
    now: datetime | None = None,
) -> list[TrafficFlowSite]:
    """Group lane detectors at the same physical site and direction."""
    located = [item for item in measurements if item.point is not None]
    if not located:
        return []

    reference_latitude = sum(item.point[1] for item in located if item.point) / len(
        located
    )
    earth_radius_m = 6_371_000.0
    cos_latitude = math.cos(math.radians(reference_latitude))
    cell_size = TRAFFIC_FLOW_SITE_CLUSTER_METERS
    parents = list(range(len(located)))

    def _find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def _union(left: int, right: int) -> None:
        left_root = _find(left)
        right_root = _find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    projected: list[tuple[float, float]] = []
    buckets: dict[tuple[str, int, int], list[int]] = {}
    for index, item in enumerate(located):
        point = item.point
        if point is None:
            continue
        longitude, latitude = point
        x = earth_radius_m * math.radians(longitude) * cos_latitude
        y = earth_radius_m * math.radians(latitude)
        projected.append((x, y))
        side = str(item.measurement_side or "unknown").strip().lower()
        bucket_x = math.floor(x / cell_size)
        bucket_y = math.floor(y / cell_size)
        for offset_x in (-1, 0, 1):
            for offset_y in (-1, 0, 1):
                for other in buckets.get(
                    (side, bucket_x + offset_x, bucket_y + offset_y), []
                ):
                    other_x, other_y = projected[other]
                    if math.hypot(x - other_x, y - other_y) <= cell_size:
                        _union(index, other)
        buckets.setdefault((side, bucket_x, bucket_y), []).append(index)

    grouped: dict[int, list[TrafficFlowMeasurement]] = {}
    for index, item in enumerate(located):
        grouped.setdefault(_find(index), []).append(item)

    sites: list[TrafficFlowSite] = []
    for group in grouped.values():
        points = [item.point for item in group if item.point is not None]
        if not points:
            continue
        longitude = sum(point[0] for point in points) / len(points)
        latitude = sum(point[1] for point in points) / len(points)
        county_values = [item.county_no for item in group if item.county_no is not None]
        side_values = [item.measurement_side for item in group if item.measurement_side]
        lanes = tuple(
            sorted(
                {item.specific_lane for item in group if item.specific_lane},
                key=lambda value: (
                    _as_int(re.sub(r"\D", "", value)) is None,
                    _as_int(re.sub(r"\D", "", value)) or 0,
                    value,
                ),
            )
        )
        site_ids = tuple(
            sorted(
                {item.site_id for item in group},
                key=lambda value: (
                    not value.isdigit(),
                    int(value) if value.isdigit() else value,
                ),
            )
        )
        sites.append(
            TrafficFlowSite(
                site_ids=site_ids,
                latitude=latitude,
                longitude=longitude,
                county_no=county_values[0] if county_values else None,
                measurement_side=side_values[0] if side_values else None,
                lanes=lanes,
                distance_km=_haversine_km(
                    origin_longitude,
                    origin_latitude,
                    longitude,
                    latitude,
                ),
                snapshot=traffic_flow_snapshot(group, now=now),
            )
        )

    return sorted(
        sites,
        key=lambda site: (
            site.distance_km,
            site.measurement_side or "",
            site.site_key,
        ),
    )


async def _async_post_xml(hass: HomeAssistant, payload: str) -> str:
    session = aiohttp_client.async_get_clientsession(hass)
    try:
        async with asyncio.timeout(20):
            async with session.post(
                TRAFIKVERKET_DATACACHE_URL,
                data=payload.encode("utf-8"),
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "User-Agent": get_user_agent(hass),
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
                return response_text
    except TrafikinfoError:
        raise
    except TimeoutError as err:
        raise TrafikinfoAPIError(
            "Request timeout - Trafikverket API not responding"
        ) from err
    except aiohttp.ClientError as err:
        raise TrafikinfoAPIError(f"Connection error: {err}") from err


async def async_fetch_traffic_flow_sites(
    hass: HomeAssistant,
    api_key: str,
    *,
    latitude: float,
    longitude: float,
    radius_km: float,
    county_no: str | None = None,
) -> list[TrafficFlowSite]:
    """Discover and group recent traffic-flow detectors."""
    request = build_traffic_flow_discovery_request_xml(
        api_key,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        county_no=county_no,
    )
    response_text = await _async_post_xml(hass, request)
    snapshot = parse_traffic_flow_response(response_text)
    return group_traffic_flow_sites(
        snapshot.measurements,
        origin_latitude=latitude,
        origin_longitude=longitude,
    )


class TrafficFlowCoordinator(DataUpdateCoordinator[TrafficFlowSnapshot]):
    """Fetch current data for one selected traffic-flow detector group."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._api_key = str(entry.data.get(CONF_API_KEY, "")).strip()
        raw_site_ids = entry.data.get(CONF_TRAFFIC_FLOW_SITE_IDS, [])
        self._site_ids = (
            tuple(str(value).strip() for value in raw_site_ids if str(value).strip())
            if isinstance(raw_site_ids, list)
            else ()
        )
        self._site_label = str(entry.data.get(CONF_TRAFFIC_FLOW_SITE_LABEL, "")).strip()
        self._latitude = float(entry.data.get(CONF_TRAFFIC_FLOW_SITE_LATITUDE, 0.0))
        self._longitude = float(entry.data.get(CONF_TRAFFIC_FLOW_SITE_LONGITUDE, 0.0))
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_traffic_flow",
            update_interval=DEFAULT_TRAFFIC_FLOW_SCAN_INTERVAL,
            always_update=False,
            config_entry=entry,
        )

    @property
    def site_ids(self) -> tuple[str, ...]:
        return self._site_ids

    @property
    def site_label(self) -> str:
        return self._site_label

    @property
    def latitude(self) -> float:
        return self._latitude

    @property
    def longitude(self) -> float:
        return self._longitude

    async def _async_update_data(self) -> TrafficFlowSnapshot:
        if not self._api_key:
            raise ConfigEntryAuthFailed("Missing API key")
        if not self._site_ids:
            raise UpdateFailed("No traffic-flow detector IDs are configured")

        request = build_traffic_flow_site_request_xml(
            self._api_key, site_ids=self._site_ids
        )
        try:
            response_text = await _async_post_xml(self.hass, request)
            return parse_traffic_flow_response(response_text)
        except TrafikinfoAuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TrafikinfoError as err:
            raise UpdateFailed(str(err)) from err
        except Exception as err:
            raise UpdateFailed(
                f"Unexpected error fetching Trafikverket traffic-flow data: {err}"
            ) from err
