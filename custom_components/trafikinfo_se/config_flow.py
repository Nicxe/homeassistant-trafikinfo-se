"""Config flow for Trafikinfo SE."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any
import xml.etree.ElementTree as ET

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.selector import selector

from .const import (
    CONF_API_KEY,
    CONF_LATITUDE,
    CONF_LOCATION,
    CONF_LONGITUDE,
    CONF_MAX_ITEMS,
    CONF_MESSAGE_TYPES,
    CONF_RADIUS_KM,
    CONF_SCAN_INTERVAL,
    DEFAULT_RADIUS_KM,
    DEFAULT_MAX_ITEMS,
    DEFAULT_MESSAGE_TYPES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
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

    VERSION = 3

    def __init__(self) -> None:
        self._api_key: str | None = None

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
                    # Only allow one entry by default (whole Sweden, single API key).
                    await self.async_set_unique_id("trafikinfo_se")
                    self._abort_if_unique_id_configured()

                    self._api_key = api_key
                    return await self.async_step_options()

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_options(self, user_input: dict[str, Any] | None = None):
        """Second step: pick options (scan interval, max items, categories)."""
        if not self._api_key:
            # If the flow is resumed without stored state, go back to API key step.
            return await self.async_step_user()

        if user_input is not None:
            loc = user_input.get(CONF_LOCATION) or {}
            lat = float(loc.get("latitude", self.hass.config.latitude))
            lon = float(loc.get("longitude", self.hass.config.longitude))
            radius_km = float(user_input.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM))

            scan_minutes = int(
                user_input.get(CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds() / 60))
            )
            max_items = int(user_input.get(CONF_MAX_ITEMS, DEFAULT_MAX_ITEMS))
            msg_types = user_input.get(CONF_MESSAGE_TYPES)
            if not isinstance(msg_types, list) or not msg_types:
                msg_types = list(DEFAULT_MESSAGE_TYPES)
            data = {
                CONF_API_KEY: self._api_key,
                CONF_LATITUDE: lat,
                CONF_LONGITUDE: lon,
                CONF_RADIUS_KM: radius_km,
                CONF_SCAN_INTERVAL: scan_minutes,
                CONF_MAX_ITEMS: max_items,
                CONF_MESSAGE_TYPES: list(msg_types),
            }
            return self.async_create_entry(title="Trafikinfo SE", data=data)

        options = [{"label": s, "value": s} for s in DEFAULT_MESSAGE_TYPES]
        schema = vol.Schema(
            {
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
        )
        return self.async_show_form(step_id="options", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return TrafikinfoSEOptionsFlowHandler(config_entry)


class TrafikinfoSEOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Trafikinfo SE options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Manage the options."""
        if user_input is not None:
            data = dict(self._config_entry.options)
            loc = user_input.get(CONF_LOCATION) or {}
            lat = float(loc.get("latitude", self.hass.config.latitude))
            lon = float(loc.get("longitude", self.hass.config.longitude))
            radius_km = float(user_input.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM))
            scan_minutes = int(user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL.total_seconds() / 60))
            max_items = int(user_input.get(CONF_MAX_ITEMS, DEFAULT_MAX_ITEMS))
            msg_types = user_input.get(CONF_MESSAGE_TYPES)
            if not isinstance(msg_types, list) or not msg_types:
                msg_types = list(DEFAULT_MESSAGE_TYPES)
            data.update(
                {
                    CONF_LATITUDE: lat,
                    CONF_LONGITUDE: lon,
                    CONF_RADIUS_KM: radius_km,
                    CONF_SCAN_INTERVAL: scan_minutes,
                    CONF_MAX_ITEMS: max_items,
                    CONF_MESSAGE_TYPES: list(msg_types),
                }
            )
            return self.async_create_entry(title="", data=data)

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
        default_radius = float(
            self._config_entry.options.get(
                CONF_RADIUS_KM,
                self._config_entry.data.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM),
            )
        )

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
        default_msg_types = list(
            self._config_entry.options.get(
                CONF_MESSAGE_TYPES,
                self._config_entry.data.get(CONF_MESSAGE_TYPES, DEFAULT_MESSAGE_TYPES),
            )
        )
        options = [{"label": s, "value": s} for s in DEFAULT_MESSAGE_TYPES]
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_LOCATION,
                    default={"latitude": default_lat, "longitude": default_lon},
                ): selector({"location": {}}),
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
        )

        return self.async_show_form(step_id="init", data_schema=schema)


