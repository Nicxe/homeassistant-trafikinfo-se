"""Config flow for Trafikinfo SE."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any
import xml.etree.ElementTree as ET

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.selector import selector

from .const import (
    CONF_API_KEY,
    CONF_COUNTIES,
    CONF_FILTER_MODE,
    CONF_LATITUDE,
    CONF_LOCATION,
    CONF_LONGITUDE,
    CONF_MAX_ITEMS,
    CONF_MESSAGE_TYPES,
    CONF_RADIUS_KM,
    CONF_SCAN_INTERVAL,
    COUNTY_ALL,
    COUNTIES,
    DEFAULT_COUNTIES,
    DEFAULT_FILTER_MODE,
    DEFAULT_RADIUS_KM,
    DEFAULT_MAX_ITEMS,
    DEFAULT_MESSAGE_TYPES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FILTER_MODE_COORDINATE,
    FILTER_MODE_COUNTY,
    SITUATION_SCHEMA_VERSION,
    TRAFIKVERKET_DATACACHE_URL,
)

_LOGGER = logging.getLogger(__name__)


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""


@dataclass(frozen=True, slots=True)
class _TestResult:
    ok: bool
    error_message: str | None = None


def _build_test_request_xml(api_key: str) -> str:
    # Minimal query to validate the API key.
    # Docs: https://data.trafikverket.se/documentation/datacache/the-request
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<REQUEST>"
        f'<LOGIN authenticationkey="{api_key}" />'
        f'<QUERY objecttype="Situation" namespace="Road.TrafficInfo" schemaversion="{SITUATION_SCHEMA_VERSION}" limit="1">'
        "<INCLUDE>Id</INCLUDE>"
        "<INCLUDE>Deviation.Suspended</INCLUDE>"
        "</QUERY>"
        "</REQUEST>"
    )


def _parse_error_message(xml_text: str) -> str | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    # The response includes RESULT/ERROR with MESSAGE (see XSD and docs).
    msg = root.findtext(".//ERROR/MESSAGE")
    if msg:
        return msg.strip()
    return None


async def _async_test_api_key(hass: HomeAssistant, api_key: str) -> _TestResult:
    session = aiohttp_client.async_get_clientsession(hass)
    payload = _build_test_request_xml(api_key)

    try:
        async with session.post(
            TRAFIKVERKET_DATACACHE_URL,
            data=payload.encode("utf-8"),
            headers={"Content-Type": "text/xml; charset=utf-8"},
            timeout=15,
        ) as resp:
            text = await resp.text()
            if resp.status != 200:
                _LOGGER.debug(
                    "Trafikverket test request failed: HTTP %s body=%s",
                    resp.status,
                    text[:500],
                )
                raise CannotConnect(f"HTTP {resp.status}")

    except CannotConnect:
        raise
    except Exception as err:
        raise CannotConnect(str(err)) from err

    err_msg = _parse_error_message(text)
    if err_msg:
        # Most auth/key issues are returned as ERROR/MESSAGE.
        return _TestResult(ok=False, error_message=err_msg)

    return _TestResult(ok=True)


class TrafikinfoSEConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Trafikinfo SE."""

    VERSION = 5

    def __init__(self) -> None:
        self._api_key: str | None = None
        self._filter_mode: str = DEFAULT_FILTER_MODE
        self._reconfigure_entry: config_entries.ConfigEntry | None = None
        self._reconfigure_defaults: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = str(user_input.get(CONF_API_KEY, "")).strip()
            if not api_key:
                errors["base"] = "invalid_auth"
            else:
                try:
                    res = await _async_test_api_key(self.hass, api_key)
                    if not res.ok:
                        raise InvalidAuth(res.error_message or "invalid auth")
                except InvalidAuth as err:
                    _LOGGER.debug("Invalid auth during config: %s", err)
                    errors["base"] = "invalid_auth"
                except CannotConnect as err:
                    _LOGGER.debug("Cannot connect during config: %s", err)
                    errors["base"] = "cannot_connect"
                except Exception as err:
                    _LOGGER.exception("Unexpected exception during config: %s", err)
                    errors["base"] = "unknown"
                else:
                    self._api_key = api_key
                    return await self.async_step_filter_mode()

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        """Handle reconfigure initiated from the UI on an existing entry."""
        entry = self.hass.config_entries.async_get_entry(self.context.get("entry_id"))
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        # Store entry and defaults for later steps
        self._reconfigure_entry = entry

        mode = str(entry.options.get(CONF_FILTER_MODE, entry.data.get(CONF_FILTER_MODE, DEFAULT_FILTER_MODE)))
        if mode not in (FILTER_MODE_COORDINATE, FILTER_MODE_COUNTY):
            # Backward compatibility for earlier "sweden" mode or unknown values.
            mode = FILTER_MODE_COUNTY

        default_lat = float(entry.options.get(CONF_LATITUDE, entry.data.get(CONF_LATITUDE, self.hass.config.latitude)))
        default_lon = float(entry.options.get(CONF_LONGITUDE, entry.data.get(CONF_LONGITUDE, self.hass.config.longitude)))
        default_location = entry.options.get(
            CONF_LOCATION,
            entry.data.get(CONF_LOCATION, {"latitude": default_lat, "longitude": default_lon}),
        )
        default_radius = float(entry.options.get(CONF_RADIUS_KM, entry.data.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM)))
        default_counties = entry.options.get(CONF_COUNTIES, entry.data.get(CONF_COUNTIES, list(DEFAULT_COUNTIES)))
        if not isinstance(default_counties, list):
            default_counties = list(DEFAULT_COUNTIES)

        default_scan = int(
            entry.options.get(
                CONF_SCAN_INTERVAL,
                entry.data.get(CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds() / 60)),
            )
        )
        default_max = int(entry.options.get(CONF_MAX_ITEMS, entry.data.get(CONF_MAX_ITEMS, DEFAULT_MAX_ITEMS)))
        default_msg_types = entry.options.get(CONF_MESSAGE_TYPES, entry.data.get(CONF_MESSAGE_TYPES, DEFAULT_MESSAGE_TYPES))
        if not isinstance(default_msg_types, list) or not default_msg_types:
            default_msg_types = list(DEFAULT_MESSAGE_TYPES)

        self._reconfigure_defaults = {
            CONF_FILTER_MODE: mode,
            CONF_LOCATION: default_location,
            CONF_RADIUS_KM: default_radius,
            CONF_COUNTIES: list(default_counties),
            CONF_SCAN_INTERVAL: default_scan,
            CONF_MAX_ITEMS: default_max,
            CONF_MESSAGE_TYPES: list(default_msg_types),
            CONF_NAME: entry.title or "Trafikinfo SE",
        }

        return await self.async_step_reconfigure_filter_mode(user_input)

    async def async_step_reconfigure_filter_mode(self, user_input: dict[str, Any] | None = None):
        if self._reconfigure_entry is None:
            return self.async_abort(reason="entry_not_found")

        if user_input is not None:
            mode = str(user_input.get(CONF_FILTER_MODE, DEFAULT_FILTER_MODE) or DEFAULT_FILTER_MODE)
            if mode not in (FILTER_MODE_COORDINATE, FILTER_MODE_COUNTY):
                mode = DEFAULT_FILTER_MODE
            self._filter_mode = mode
            if mode == FILTER_MODE_COUNTY:
                return await self.async_step_reconfigure_counties()
            return await self.async_step_reconfigure_coordinate()

        mode_options = [
            {"label": "Koordinat + radie", "value": FILTER_MODE_COORDINATE},
            {"label": "Län / Hela Sverige", "value": FILTER_MODE_COUNTY},
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_FILTER_MODE, default=self._reconfigure_defaults.get(CONF_FILTER_MODE, DEFAULT_FILTER_MODE)): selector(
                    {"select": {"options": mode_options, "mode": "dropdown"}}
                )
            }
        )
        return self.async_show_form(step_id="reconfigure_filter_mode", data_schema=schema)

    async def async_step_reconfigure_coordinate(self, user_input: dict[str, Any] | None = None):
        if self._reconfigure_entry is None:
            return self.async_abort(reason="entry_not_found")
        entry = self._reconfigure_entry

        if user_input is not None:
            name, scan_minutes, max_items, msg_types = self._finalize_common(user_input)
            loc = user_input.get(CONF_LOCATION) or {}
            lat = float(loc.get("latitude", self.hass.config.latitude))
            lon = float(loc.get("longitude", self.hass.config.longitude))
            radius_km = float(user_input.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM))

            new_data = dict(entry.data)
            new_data.update(
                {
                    CONF_FILTER_MODE: FILTER_MODE_COORDINATE,
                    CONF_LATITUDE: lat,
                    CONF_LONGITUDE: lon,
                    CONF_RADIUS_KM: radius_km,
                    CONF_SCAN_INTERVAL: scan_minutes,
                    CONF_MAX_ITEMS: max_items,
                    CONF_MESSAGE_TYPES: list(msg_types),
                }
            )

            # Keep options message_types if it exists; otherwise align it with data.
            new_options = dict(entry.options)
            new_options.setdefault(CONF_MESSAGE_TYPES, list(msg_types))

            if name and name != (entry.title or ""):
                new_title = name
            else:
                new_title = entry.title or "Trafikinfo SE"

            return self.async_update_reload_and_abort(
                entry=entry,
                data=new_data,
                options=new_options,
                reason="reconfigured_successful",
                title=new_title,
            )

        schema_dict: dict[vol.Marker, Any] = {
            vol.Optional(CONF_LOCATION, default=self._reconfigure_defaults.get(CONF_LOCATION)): selector({"location": {}}),
            vol.Optional(CONF_RADIUS_KM, default=self._reconfigure_defaults.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM)): selector(
                {
                    "number": {
                        "min": 1,
                        "max": 250,
                        "step": 1,
                        "unit_of_measurement": "km",
                        "mode": "slider",
                    }
                }
            ),
        }
        schema_dict.update(self._common_schema(default_name=self._reconfigure_defaults.get(CONF_NAME, "Trafikinfo SE")))
        return self.async_show_form(step_id="reconfigure_coordinate", data_schema=vol.Schema(schema_dict))

    async def async_step_reconfigure_counties(self, user_input: dict[str, Any] | None = None):
        if self._reconfigure_entry is None:
            return self.async_abort(reason="entry_not_found")
        entry = self._reconfigure_entry
        errors: dict[str, str] = {}

        if user_input is not None:
            name, scan_minutes, max_items, msg_types = self._finalize_common(user_input)
            selected = user_input.get(CONF_COUNTIES)
            if not isinstance(selected, list) or not selected:
                errors["base"] = "missing_counties"
            else:
                counties = [str(x) for x in selected if str(x).strip()]
                if not counties:
                    errors["base"] = "missing_counties"
                else:
                    if COUNTY_ALL in counties:
                        counties = [COUNTY_ALL]
                    new_data = dict(entry.data)
                    new_data.update(
                        {
                            CONF_FILTER_MODE: FILTER_MODE_COUNTY,
                            CONF_COUNTIES: counties,
                            CONF_SCAN_INTERVAL: scan_minutes,
                            CONF_MAX_ITEMS: max_items,
                            CONF_MESSAGE_TYPES: list(msg_types),
                        }
                    )
                    new_options = dict(entry.options)
                    new_options.setdefault(CONF_MESSAGE_TYPES, list(msg_types))

                    if name and name != (entry.title or ""):
                        new_title = name
                    else:
                        new_title = entry.title or "Trafikinfo SE"

                    return self.async_update_reload_and_abort(
                        entry=entry,
                        data=new_data,
                        options=new_options,
                        reason="reconfigured_successful",
                        title=new_title,
                    )

        county_options = [{"label": "Hela Sverige", "value": COUNTY_ALL}] + [
            {"label": name, "value": code} for code, name in COUNTIES.items()
        ]
        schema_dict: dict[vol.Marker, Any] = {
            vol.Optional(CONF_COUNTIES, default=self._reconfigure_defaults.get(CONF_COUNTIES, list(DEFAULT_COUNTIES))): selector(
                {"select": {"options": county_options, "multiple": True, "mode": "list"}}
            ),
        }
        schema_dict.update(self._common_schema(default_name=self._reconfigure_defaults.get(CONF_NAME, "Trafikinfo SE")))
        return self.async_show_form(
            step_id="reconfigure_counties", data_schema=vol.Schema(schema_dict), errors=errors
        )

    async def async_step_filter_mode(self, user_input: dict[str, Any] | None = None):
        """Second step: choose how to filter events (interactive UI via multi-step)."""
        if not self._api_key:
            # If the flow is resumed without stored state, go back to API key step.
            return await self.async_step_user()

        if user_input is not None:
            mode = str(user_input.get(CONF_FILTER_MODE, DEFAULT_FILTER_MODE) or DEFAULT_FILTER_MODE)
            if mode not in (FILTER_MODE_COORDINATE, FILTER_MODE_COUNTY):
                mode = DEFAULT_FILTER_MODE
            self._filter_mode = mode
            if mode == FILTER_MODE_COUNTY:
                return await self.async_step_configure_counties()
            return await self.async_step_configure_coordinate()

        mode_options = [
            {"label": "Koordinat + radie", "value": FILTER_MODE_COORDINATE},
            {"label": "Län / Hela Sverige", "value": FILTER_MODE_COUNTY},
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_FILTER_MODE, default=DEFAULT_FILTER_MODE): selector(
                    {"select": {"options": mode_options, "mode": "dropdown"}}
                ),
            }
        )
        return self.async_show_form(step_id="filter_mode", data_schema=schema)

    def _common_schema(self, *, default_name: str) -> dict[vol.Marker, Any]:
        options = [{"label": s, "value": s} for s in DEFAULT_MESSAGE_TYPES]
        return {
            vol.Optional(CONF_NAME, default=default_name): str,
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=int(DEFAULT_SCAN_INTERVAL.total_seconds() / 60),
            ): selector(
                {
                    "number": {
                        "min": 1,
                        "max": 120,
                        "step": 1,
                        "unit_of_measurement": "min",
                        "mode": "box",
                    }
                }
            ),
            vol.Optional(CONF_MAX_ITEMS, default=DEFAULT_MAX_ITEMS): selector(
                {"number": {"min": 0, "max": 200, "step": 1, "mode": "box"}}
            ),
            vol.Optional(CONF_MESSAGE_TYPES, default=list(DEFAULT_MESSAGE_TYPES)): selector(
                {"select": {"options": options, "multiple": True, "mode": "list"}}
            ),
        }

    def _finalize_common(self, user_input: dict[str, Any]) -> tuple[str, int, int, list[str]]:
        name = str(user_input.get(CONF_NAME) or "").strip() or "Trafikinfo SE"
        scan_minutes = int(
            user_input.get(CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds() / 60))
        )
        max_items = int(user_input.get(CONF_MAX_ITEMS, DEFAULT_MAX_ITEMS))
        msg_types = user_input.get(CONF_MESSAGE_TYPES)
        if not isinstance(msg_types, list) or not msg_types:
            msg_types = list(DEFAULT_MESSAGE_TYPES)
        return name, scan_minutes, max_items, list(msg_types)

    async def async_step_configure_coordinate(
        self, user_input: dict[str, Any] | None = None
    ):
        """Configure coordinate+radius filtering."""
        if not self._api_key:
            return await self.async_step_user()

        if user_input is not None:
            name, scan_minutes, max_items, msg_types = self._finalize_common(user_input)
            loc = user_input.get(CONF_LOCATION) or {}
            lat = float(loc.get("latitude", self.hass.config.latitude))
            lon = float(loc.get("longitude", self.hass.config.longitude))
            radius_km = float(user_input.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM))
            data = {
                CONF_API_KEY: self._api_key,
                CONF_FILTER_MODE: FILTER_MODE_COORDINATE,
                CONF_LATITUDE: lat,
                CONF_LONGITUDE: lon,
                CONF_RADIUS_KM: radius_km,
                CONF_SCAN_INTERVAL: scan_minutes,
                CONF_MAX_ITEMS: max_items,
                CONF_MESSAGE_TYPES: msg_types,
            }
            return self.async_create_entry(title=name, data=data)

        schema_dict: dict[vol.Marker, Any] = {
            vol.Optional(
                CONF_LOCATION,
                default={
                    "latitude": self.hass.config.latitude,
                    "longitude": self.hass.config.longitude,
                },
            ): selector({"location": {}}),
            vol.Optional(CONF_RADIUS_KM, default=DEFAULT_RADIUS_KM): selector(
                {
                    "number": {
                        "min": 1,
                        "max": 250,
                        "step": 1,
                        "unit_of_measurement": "km",
                        "mode": "slider",
                    }
                }
            ),
        }
        schema_dict.update(self._common_schema(default_name="Trafikinfo SE"))
        return self.async_show_form(
            step_id="configure_coordinate", data_schema=vol.Schema(schema_dict)
        )

    async def async_step_configure_counties(
        self, user_input: dict[str, Any] | None = None
    ):
        """Configure counties filtering (multi-select)."""
        if not self._api_key:
            return await self.async_step_user()

        errors: dict[str, str] = {}
        if user_input is not None:
            name, scan_minutes, max_items, msg_types = self._finalize_common(user_input)
            selected = user_input.get(CONF_COUNTIES)
            if not isinstance(selected, list) or not selected:
                errors["base"] = "missing_counties"
            else:
                counties = [str(x) for x in selected if str(x).strip()]
                if not counties:
                    errors["base"] = "missing_counties"
                else:
                    # If "Hela Sverige" is selected, normalize to only that value.
                    if COUNTY_ALL in counties:
                        counties = [COUNTY_ALL]
                    data = {
                        CONF_API_KEY: self._api_key,
                        CONF_FILTER_MODE: FILTER_MODE_COUNTY,
                        CONF_COUNTIES: counties,
                        CONF_SCAN_INTERVAL: scan_minutes,
                        CONF_MAX_ITEMS: max_items,
                        CONF_MESSAGE_TYPES: msg_types,
                    }
                    return self.async_create_entry(title=name, data=data)

        county_options = [{"label": "Hela Sverige", "value": COUNTY_ALL}] + [
            {"label": name, "value": code} for code, name in COUNTIES.items()
        ]
        schema_dict: dict[vol.Marker, Any] = {
            vol.Optional(CONF_COUNTIES, default=list(DEFAULT_COUNTIES)): selector(
                {"select": {"options": county_options, "multiple": True, "mode": "list"}}
            ),
        }
        schema_dict.update(self._common_schema(default_name="Trafikinfo SE"))
        return self.async_show_form(
            step_id="configure_counties", data_schema=vol.Schema(schema_dict), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return TrafikinfoSEOptionsFlowHandler(config_entry)


class TrafikinfoSEOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Trafikinfo SE options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._filter_mode: str = str(
            config_entry.options.get(
                CONF_FILTER_MODE,
                config_entry.data.get(CONF_FILTER_MODE, DEFAULT_FILTER_MODE),
            )
        )
        if self._filter_mode not in (FILTER_MODE_COORDINATE, FILTER_MODE_COUNTY):
            self._filter_mode = DEFAULT_FILTER_MODE

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Choose filter mode, then go to a mode-specific step (interactive UI)."""
        if user_input is not None:
            mode = str(user_input.get(CONF_FILTER_MODE, DEFAULT_FILTER_MODE) or DEFAULT_FILTER_MODE)
            if mode not in (FILTER_MODE_COORDINATE, FILTER_MODE_COUNTY):
                mode = DEFAULT_FILTER_MODE
            self._filter_mode = mode
            if mode == FILTER_MODE_COUNTY:
                return await self.async_step_counties()
            return await self.async_step_coordinate()

        default_name = self._config_entry.title or "Trafikinfo SE"
        mode_options = [
            {"label": "Koordinat + radie", "value": FILTER_MODE_COORDINATE},
            {"label": "Län / Hela Sverige", "value": FILTER_MODE_COUNTY},
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_FILTER_MODE, default=self._filter_mode): selector(
                    {"select": {"options": mode_options, "mode": "dropdown"}}
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    def _common_defaults(self) -> dict[str, Any]:
        default_name = self._config_entry.title or "Trafikinfo SE"
        default_scan = int(
            self._config_entry.options.get(
                CONF_SCAN_INTERVAL,
                self._config_entry.data.get(
                    CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds() / 60)
                ),
            )
        )
        default_max = int(
            self._config_entry.options.get(
                CONF_MAX_ITEMS,
                self._config_entry.data.get(CONF_MAX_ITEMS, DEFAULT_MAX_ITEMS),
            )
        )
        default_msg_types = self._config_entry.options.get(
            CONF_MESSAGE_TYPES,
            self._config_entry.data.get(CONF_MESSAGE_TYPES, DEFAULT_MESSAGE_TYPES),
        )
        if not isinstance(default_msg_types, list) or not default_msg_types:
            default_msg_types = list(DEFAULT_MESSAGE_TYPES)
        return {
            "name": default_name,
            "scan_interval": default_scan,
            "max_items": default_max,
            "message_types": list(default_msg_types),
        }

    def _common_schema(self, *, default_name: str, default_scan: int, default_max: int, default_msg_types: list[str]) -> dict[vol.Marker, Any]:
        options = [{"label": s, "value": s} for s in DEFAULT_MESSAGE_TYPES]
        return {
            vol.Optional(CONF_NAME, default=default_name): str,
            vol.Optional(CONF_SCAN_INTERVAL, default=default_scan): selector(
                {
                    "number": {
                        "min": 1,
                        "max": 120,
                        "step": 1,
                        "unit_of_measurement": "min",
                        "mode": "box",
                    }
                }
            ),
            vol.Optional(CONF_MAX_ITEMS, default=default_max): selector(
                {"number": {"min": 0, "max": 200, "step": 1, "mode": "box"}}
            ),
            vol.Optional(CONF_MESSAGE_TYPES, default=default_msg_types): selector(
                {"select": {"options": options, "multiple": True, "mode": "list"}}
            ),
        }

    def _finalize_common(self, user_input: dict[str, Any]) -> tuple[str | None, int, int, list[str]]:
        name = str(user_input.get(CONF_NAME) or "").strip()
        scan_minutes = int(
            user_input.get(
                CONF_SCAN_INTERVAL,
                self._config_entry.options.get(
                    CONF_SCAN_INTERVAL,
                    self._config_entry.data.get(
                        CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds() / 60)
                    ),
                ),
            )
        )
        max_items = int(
            user_input.get(
                CONF_MAX_ITEMS,
                self._config_entry.options.get(
                    CONF_MAX_ITEMS, self._config_entry.data.get(CONF_MAX_ITEMS, DEFAULT_MAX_ITEMS)
                ),
            )
        )
        msg_types = user_input.get(CONF_MESSAGE_TYPES)
        if not isinstance(msg_types, list) or not msg_types:
            msg_types = list(
                self._config_entry.options.get(
                    CONF_MESSAGE_TYPES,
                    self._config_entry.data.get(CONF_MESSAGE_TYPES, DEFAULT_MESSAGE_TYPES),
                )
            )
        if not msg_types:
            msg_types = list(DEFAULT_MESSAGE_TYPES)
        return (name or None), scan_minutes, max_items, list(msg_types)

    async def async_step_coordinate(self, user_input: dict[str, Any] | None = None):
        """Options: configure coordinate+radius."""
        common = self._common_defaults()
        default_lat = float(
            self._config_entry.options.get(
                CONF_LATITUDE,
                self._config_entry.data.get(CONF_LATITUDE, self.hass.config.latitude),
            )
        )
        default_lon = float(
            self._config_entry.options.get(
                CONF_LONGITUDE,
                self._config_entry.data.get(CONF_LONGITUDE, self.hass.config.longitude),
            )
        )
        default_location = self._config_entry.options.get(
            CONF_LOCATION,
            self._config_entry.data.get(CONF_LOCATION, {"latitude": default_lat, "longitude": default_lon}),
        )
        default_radius = float(
            self._config_entry.options.get(
                CONF_RADIUS_KM,
                self._config_entry.data.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM),
            )
        )

        if user_input is not None:
            data = dict(self._config_entry.options)
            name, scan_minutes, max_items, msg_types = self._finalize_common(user_input)
            if name and name != (self._config_entry.title or ""):
                self.hass.config_entries.async_update_entry(self._config_entry, title=name)
            loc = user_input.get(CONF_LOCATION) or {}
            lat = float(loc.get("latitude", self.hass.config.latitude))
            lon = float(loc.get("longitude", self.hass.config.longitude))
            radius_km = float(user_input.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM))
            data.update(
                {
                    CONF_FILTER_MODE: FILTER_MODE_COORDINATE,
                    CONF_LATITUDE: lat,
                    CONF_LONGITUDE: lon,
                    CONF_RADIUS_KM: radius_km,
                    CONF_SCAN_INTERVAL: scan_minutes,
                    CONF_MAX_ITEMS: max_items,
                    CONF_MESSAGE_TYPES: list(msg_types),
                }
            )
            return self.async_create_entry(title="", data=data)

        schema_dict: dict[vol.Marker, Any] = {
            vol.Optional(CONF_LOCATION, default=default_location): selector({"location": {}}),
            vol.Optional(CONF_RADIUS_KM, default=default_radius): selector(
                {
                    "number": {
                        "min": 1,
                        "max": 250,
                        "step": 1,
                        "unit_of_measurement": "km",
                        "mode": "slider",
                    }
                }
            ),
        }
        schema_dict.update(
            self._common_schema(
                default_name=common["name"],
                default_scan=common["scan_interval"],
                default_max=common["max_items"],
                default_msg_types=common["message_types"],
            )
        )
        return self.async_show_form(step_id="coordinate", data_schema=vol.Schema(schema_dict))

    async def async_step_counties(self, user_input: dict[str, Any] | None = None):
        """Options: configure county filtering (multi-select; includes Sweden-wide)."""
        common = self._common_defaults()
        default_counties = self._config_entry.options.get(
            CONF_COUNTIES,
            self._config_entry.data.get(CONF_COUNTIES, list(DEFAULT_COUNTIES)),
        )
        if not isinstance(default_counties, list):
            default_counties = list(DEFAULT_COUNTIES)

        errors: dict[str, str] = {}
        if user_input is not None:
            data = dict(self._config_entry.options)
            name, scan_minutes, max_items, msg_types = self._finalize_common(user_input)
            if name and name != (self._config_entry.title or ""):
                self.hass.config_entries.async_update_entry(self._config_entry, title=name)
            selected = user_input.get(CONF_COUNTIES)
            if not isinstance(selected, list) or not selected:
                errors["base"] = "missing_counties"
            else:
                counties = [str(x) for x in selected if str(x).strip()]
                if not counties:
                    errors["base"] = "missing_counties"
                else:
                    if COUNTY_ALL in counties:
                        counties = [COUNTY_ALL]
                    data.update(
                        {
                            CONF_FILTER_MODE: FILTER_MODE_COUNTY,
                            CONF_COUNTIES: counties,
                            CONF_SCAN_INTERVAL: scan_minutes,
                            CONF_MAX_ITEMS: max_items,
                            CONF_MESSAGE_TYPES: list(msg_types),
                        }
                    )
                    return self.async_create_entry(title="", data=data)

        county_options = [{"label": "Hela Sverige", "value": COUNTY_ALL}] + [
            {"label": name, "value": code} for code, name in COUNTIES.items()
        ]
        schema_dict: dict[vol.Marker, Any] = {
            vol.Optional(CONF_COUNTIES, default=list(default_counties)): selector(
                {"select": {"options": county_options, "multiple": True, "mode": "list"}}
            ),
        }
        schema_dict.update(
            self._common_schema(
                default_name=common["name"],
                default_scan=common["scan_interval"],
                default_max=common["max_items"],
                default_msg_types=common["message_types"],
            )
        )
        return self.async_show_form(step_id="counties", data_schema=vol.Schema(schema_dict), errors=errors)


