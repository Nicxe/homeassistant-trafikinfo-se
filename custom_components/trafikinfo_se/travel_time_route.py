"""TravelTimeRoute support for Trafikinfo SE."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import logging
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
    CONF_ROUTE_ID,
    DEFAULT_TRAVEL_TIME_ROUTE_SCAN_INTERVAL,
    DOMAIN,
    TRAFIKVERKET_DATACACHE_URL,
    TRAVEL_TIME_ROUTE_SCHEMA_VERSION,
    get_user_agent,
)
from .coordinator import (
    TrafikinfoAPIError,
    TrafikinfoAuthenticationError,
    TrafikinfoError,
    TrafikinfoParseError,
)

_LOGGER = logging.getLogger(__name__)


def _strip(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped else None


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
    lowered = value.lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    return None


def _as_dt(value: str | None) -> datetime | None:
    value = _strip(value)
    if value is None:
        return None
    return dt_util.parse_datetime(value)


@dataclass(frozen=True, slots=True)
class TravelTimeRouteCatalogEntry:
    """A selectable TravelTimeRoute from Trafikverket."""

    route_id: str
    name: str
    county_no: int | None

    def option_label(self) -> str:
        if self.county_no is None:
            return self.name
        return f"{self.name} (county {self.county_no})"


@dataclass(frozen=True, slots=True)
class TravelTimeRouteSnapshot:
    """Current state for one TravelTimeRoute."""

    route_id: str
    version_id: str | None
    name: str
    country_code: str | None
    county_no: int | None
    average_functional_road_class: int | None
    route_owner: int | None
    travel_time_s: float | None
    free_flow_travel_time_s: float | None
    expected_free_flow_travel_time_s: float | None
    delay_s: float | None
    delay_percent: float | None
    speed_kmh: float | None
    traffic_status: str | None
    status_code: str | None
    measure_time: datetime | None
    modified_time: datetime | None
    geometry_wgs84: str | None
    length_m: float | None
    deleted: bool | None

    def as_dict(self) -> dict[str, Any]:
        """Return a user-facing dict representation for templates/cards."""

        def _dt(value: datetime | None) -> str | None:
            return value.isoformat() if isinstance(value, datetime) else None

        def _minutes(value: float | None) -> float | None:
            if value is None:
                return None
            return round(value / 60, 2)

        return {
            "route_id": self.route_id,
            "version_id": self.version_id,
            "name": self.name,
            "country_code": self.country_code,
            "county_no": self.county_no,
            "average_functional_road_class": self.average_functional_road_class,
            "route_owner": self.route_owner,
            "travel_time_min": _minutes(self.travel_time_s),
            "free_flow_time_min": _minutes(self.free_flow_travel_time_s),
            "expected_free_flow_time_min": _minutes(
                self.expected_free_flow_travel_time_s
            ),
            "delay_min": _minutes(self.delay_s),
            "delay_percent": round(self.delay_percent, 2)
            if self.delay_percent is not None
            else None,
            "speed_kmh": round(self.speed_kmh, 2)
            if self.speed_kmh is not None
            else None,
            "traffic_status": self.traffic_status,
            "status_code": self.status_code,
            "measure_time": _dt(self.measure_time),
            "modified_time": _dt(self.modified_time),
            "geometry_wgs84": self.geometry_wgs84,
            "length_m": round(self.length_m, 2) if self.length_m is not None else None,
        }


def _parse_error_message(root: ET.Element) -> str | None:
    msg = root.findtext(".//{*}ERROR/{*}MESSAGE")
    return msg.strip() if isinstance(msg, str) and msg.strip() else None


def build_route_catalog_request_xml(
    api_key: str, *, county_no: str | None = None, limit: int = 2000
) -> str:
    """Build a route catalog request for config/reconfigure flows."""

    county_filter = ""
    county_no = _strip(county_no)
    if county_no and county_no != "all":
        county_filter = f'<EQ name="CountyNo" value="{quote(county_no, safe="")}" />'

    filter_body = (
        "<FILTER><AND>"
        '<EQ name="Deleted" value="false" />'
        f"{county_filter}"
        "</AND></FILTER>"
    )

    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<REQUEST>"
        f'<LOGIN authenticationkey="{api_key}" />'
        f'<QUERY objecttype="TravelTimeRoute" namespace="Road.TrafficInfo" '
        f'schemaversion="{TRAVEL_TIME_ROUTE_SCHEMA_VERSION}" limit="{int(limit)}">'
        f"{filter_body}"
        "<INCLUDE>Id</INCLUDE>"
        "<INCLUDE>Name</INCLUDE>"
        "<INCLUDE>CountyNo</INCLUDE>"
        "</QUERY>"
        "</REQUEST>"
    )


def build_route_request_xml(api_key: str, *, route_id: str) -> str:
    """Build a request for one selected TravelTimeRoute."""

    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<REQUEST>"
        f'<LOGIN authenticationkey="{api_key}" />'
        f'<QUERY objecttype="TravelTimeRoute" namespace="Road.TrafficInfo" '
        f'schemaversion="{TRAVEL_TIME_ROUTE_SCHEMA_VERSION}" limit="1">'
        "<FILTER><AND>"
        '<EQ name="Deleted" value="false" />'
        f'<EQ name="Id" value="{route_id}" />'
        "</AND></FILTER>"
        "<INCLUDE>Id</INCLUDE>"
        "<INCLUDE>VersionId</INCLUDE>"
        "<INCLUDE>AverageFunctionalRoadClass</INCLUDE>"
        "<INCLUDE>CountryCode</INCLUDE>"
        "<INCLUDE>CountyNo</INCLUDE>"
        "<INCLUDE>ExpectedFreeFlowTravelTime</INCLUDE>"
        "<INCLUDE>FreeFlowTravelTime</INCLUDE>"
        "<INCLUDE>Length</INCLUDE>"
        "<INCLUDE>MeasureTime</INCLUDE>"
        "<INCLUDE>Name</INCLUDE>"
        "<INCLUDE>RouteOwner</INCLUDE>"
        "<INCLUDE>Speed</INCLUDE>"
        "<INCLUDE>TrafficStatus</INCLUDE>"
        "<INCLUDE>TravelTime</INCLUDE>"
        "<INCLUDE>Geometry</INCLUDE>"
        "<INCLUDE>ModifiedTime</INCLUDE>"
        "<INCLUDE>Deleted</INCLUDE>"
        "</QUERY>"
        "</REQUEST>"
    )


def parse_route_catalog_response(xml_text: str) -> list[TravelTimeRouteCatalogEntry]:
    """Parse a route catalog response."""

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as err:
        raise TrafikinfoParseError(f"Invalid XML from Trafikverket: {err}") from err

    err_msg = _parse_error_message(root)
    if err_msg:
        if "authentication" in err_msg.lower() or "invalid key" in err_msg.lower():
            raise TrafikinfoAuthenticationError(
                f"Authentication failed: {err_msg.strip()}"
            )
        raise TrafikinfoAPIError(f"Trafikverket API error: {err_msg.strip()}")

    routes: list[TravelTimeRouteCatalogEntry] = []
    for route in root.findall(".//{*}TravelTimeRoute"):
        route_id = _strip(route.findtext("./{*}Id"))
        name = _strip(route.findtext("./{*}Name"))
        if not route_id or not name:
            continue
        routes.append(
            TravelTimeRouteCatalogEntry(
                route_id=route_id,
                name=name,
                county_no=_as_int(route.findtext("./{*}CountyNo")),
            )
        )

    routes.sort(key=lambda item: (item.county_no or 0, item.name.lower(), item.route_id))
    return routes


def parse_route_response(xml_text: str) -> TravelTimeRouteSnapshot | None:
    """Parse a selected TravelTimeRoute response."""

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as err:
        raise TrafikinfoParseError(f"Invalid XML from Trafikverket: {err}") from err

    err_msg = _parse_error_message(root)
    if err_msg:
        if "authentication" in err_msg.lower() or "invalid key" in err_msg.lower():
            raise TrafikinfoAuthenticationError(
                f"Authentication failed: {err_msg.strip()}"
            )
        raise TrafikinfoAPIError(f"Trafikverket API error: {err_msg.strip()}")

    route = root.find(".//{*}TravelTimeRoute")
    if route is None:
        return None

    route_id = _strip(route.findtext("./{*}Id"))
    name = _strip(route.findtext("./{*}Name"))
    if not route_id or not name:
        raise TrafikinfoParseError("TravelTimeRoute payload is missing Id or Name")

    deleted = _as_bool(route.findtext("./{*}Deleted"))
    if deleted is True:
        return None

    travel_time_s = _as_float(route.findtext("./{*}TravelTime"))
    free_flow_s = _as_float(route.findtext("./{*}FreeFlowTravelTime"))
    expected_free_flow_s = _as_float(
        route.findtext("./{*}ExpectedFreeFlowTravelTime")
    )
    delay_s = None
    delay_percent = None
    if travel_time_s is not None and free_flow_s is not None:
        delay_s = travel_time_s - free_flow_s
        if free_flow_s > 0:
            delay_percent = (delay_s / free_flow_s) * 100

    return TravelTimeRouteSnapshot(
        route_id=route_id,
        version_id=_strip(route.findtext("./{*}VersionId")),
        name=name,
        country_code=_strip(route.findtext("./{*}CountryCode")),
        county_no=_as_int(route.findtext("./{*}CountyNo")),
        average_functional_road_class=_as_int(
            route.findtext("./{*}AverageFunctionalRoadClass")
        ),
        route_owner=_as_int(route.findtext("./{*}RouteOwner")),
        travel_time_s=travel_time_s,
        free_flow_travel_time_s=free_flow_s,
        expected_free_flow_travel_time_s=expected_free_flow_s,
        delay_s=delay_s,
        delay_percent=delay_percent,
        speed_kmh=_as_float(route.findtext("./{*}Speed")),
        traffic_status=_strip(route.findtext("./{*}TrafficStatus")),
        status_code=_strip(route.findtext("./{*}TrafficStatus")),
        measure_time=_as_dt(route.findtext("./{*}MeasureTime")),
        modified_time=_as_dt(route.findtext("./{*}ModifiedTime")),
        geometry_wgs84=_strip(route.findtext(".//{*}Geometry//{*}WGS84")),
        length_m=_as_float(route.findtext("./{*}Length")),
        deleted=deleted,
    )


async def _async_post_xml(hass: HomeAssistant, payload: str) -> str:
    session = aiohttp_client.async_get_clientsession(hass)
    async with async_timeout.timeout(20):
        async with session.post(
            TRAFIKVERKET_DATACACHE_URL,
            data=payload.encode("utf-8"),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "User-Agent": get_user_agent(hass),
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
            return text


async def async_fetch_route_catalog(
    hass: HomeAssistant, api_key: str, *, county_no: str | None = None
) -> list[TravelTimeRouteCatalogEntry]:
    """Fetch a selectable route catalog for the config flow."""

    payload = build_route_catalog_request_xml(api_key, county_no=county_no)
    try:
        response_text = await _async_post_xml(hass, payload)
        return parse_route_catalog_response(response_text)
    except TrafikinfoError:
        raise
    except asyncio.TimeoutError as err:
        raise TrafikinfoAPIError("Request timeout - Trafikverket API not responding") from err
    except aiohttp.ClientError as err:
        raise TrafikinfoAPIError(f"Connection error: {err}") from err


class TravelTimeRouteCoordinator(
    DataUpdateCoordinator[TravelTimeRouteSnapshot | None]
):
    """Fetch one selected TravelTimeRoute."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry = entry
        self._api_key = str(entry.data.get(CONF_API_KEY, "")).strip()
        self._route_id = str(entry.data.get(CONF_ROUTE_ID, "")).strip()
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_travel_time_route",
            update_interval=DEFAULT_TRAVEL_TIME_ROUTE_SCAN_INTERVAL,
            always_update=False,
        )

    @property
    def route_id(self) -> str:
        return self._route_id

    async def _async_update_data(self) -> TravelTimeRouteSnapshot | None:
        if not self._api_key:
            raise UpdateFailed("Missing API key")
        if not self._route_id:
            raise UpdateFailed("Missing route id")

        payload = build_route_request_xml(self._api_key, route_id=self._route_id)
        try:
            response_text = await _async_post_xml(self.hass, payload)
            return parse_route_response(response_text)
        except TrafikinfoError as err:
            raise UpdateFailed(str(err)) from err
        except asyncio.TimeoutError:
            raise UpdateFailed(
                "Request timeout - Trafikverket API not responding"
            ) from None
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Connection error: {err}") from err
        except Exception as err:
            raise UpdateFailed(
                f"Unexpected error fetching Trafikverket travel time data: {err}"
            ) from err
