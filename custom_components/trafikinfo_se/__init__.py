"""The Trafikinfo SE integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from time import monotonic
from typing import TYPE_CHECKING

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.util import dt as dt_util, slugify

from homeassistant.helpers import entity_registry as er

from .const import (
    ATTR_ENTRY_ID,
    ATTR_EVENT_KEY,
    ATTR_SIGNATURE,
    CONF_DISMISSED_EVENTS,
    CONF_MESSAGE_TYPES,
    DEFAULT_MESSAGE_TYPES,
    DOMAIN,
    SERVICE_DISMISS_EVENT,
    SERVICE_RESTORE_ALL_EVENTS,
    SERVICE_RESTORE_EVENT,
)
from .coordinator import TrafikinfoCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor"]


@dataclass
class TrafikinfoRuntimeData:
    """Runtime data for Trafikinfo SE integration."""

    coordinator: TrafikinfoCoordinator


if TYPE_CHECKING:
    type TrafikinfoConfigEntry = ConfigEntry[TrafikinfoRuntimeData]
else:
    TrafikinfoConfigEntry = ConfigEntry

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Service schemas
SERVICE_DISMISS_EVENT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTRY_ID): cv.string,
        vol.Required(ATTR_EVENT_KEY): cv.string,
        vol.Optional(ATTR_SIGNATURE): cv.string,
    }
)

SERVICE_RESTORE_EVENT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTRY_ID): cv.string,
        vol.Required(ATTR_EVENT_KEY): cv.string,
    }
)

SERVICE_RESTORE_ALL_EVENTS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTRY_ID): cv.string,
    }
)


def _get_dismissed_events(entry: ConfigEntry) -> dict[str, dict]:
    """Get dismissed events from entry options."""
    dismissed = entry.options.get(CONF_DISMISSED_EVENTS, {})
    if not isinstance(dismissed, dict):
        return {}
    return dismissed


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration (YAML is not supported)."""
    await _async_register_services(hass)
    return True


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register Trafikinfo SE services."""
    if hass.services.has_service(DOMAIN, SERVICE_DISMISS_EVENT):
        return  # Services already registered

    async def async_dismiss_event(call: ServiceCall) -> None:
        """Handle dismiss_event service call."""
        entry_id = call.data[ATTR_ENTRY_ID]
        event_key = call.data[ATTR_EVENT_KEY]
        signature = call.data.get(ATTR_SIGNATURE)

        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            _LOGGER.warning("Invalid entry_id for dismiss_event: %s", entry_id)
            return

        dismissed = dict(_get_dismissed_events(entry))
        dismissed[event_key] = {
            "signature": signature,
            "dismissed_at": dt_util.utcnow().isoformat(),
        }

        new_options = dict(entry.options)
        new_options[CONF_DISMISSED_EVENTS] = dismissed
        hass.config_entries.async_update_entry(entry, options=new_options)

        # Trigger coordinator refresh to update sensor state
        if hasattr(entry, "runtime_data") and entry.runtime_data:
            coordinator = entry.runtime_data.coordinator
            await coordinator.async_request_refresh()

        _LOGGER.debug("Dismissed event %s for entry %s", event_key, entry_id)

    async def async_restore_event(call: ServiceCall) -> None:
        """Handle restore_event service call."""
        entry_id = call.data[ATTR_ENTRY_ID]
        event_key = call.data[ATTR_EVENT_KEY]

        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            _LOGGER.warning("Invalid entry_id for restore_event: %s", entry_id)
            return

        dismissed = dict(_get_dismissed_events(entry))
        if event_key in dismissed:
            del dismissed[event_key]

            new_options = dict(entry.options)
            new_options[CONF_DISMISSED_EVENTS] = dismissed
            hass.config_entries.async_update_entry(entry, options=new_options)

            # Trigger coordinator refresh
            if hasattr(entry, "runtime_data") and entry.runtime_data:
                coordinator = entry.runtime_data.coordinator
                await coordinator.async_request_refresh()

            _LOGGER.debug("Restored event %s for entry %s", event_key, entry_id)

    async def async_restore_all_events(call: ServiceCall) -> None:
        """Handle restore_all_events service call."""
        entry_id = call.data[ATTR_ENTRY_ID]

        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            _LOGGER.warning("Invalid entry_id for restore_all_events: %s", entry_id)
            return

        new_options = dict(entry.options)
        new_options[CONF_DISMISSED_EVENTS] = {}
        hass.config_entries.async_update_entry(entry, options=new_options)

        # Trigger coordinator refresh
        if hasattr(entry, "runtime_data") and entry.runtime_data:
            coordinator = entry.runtime_data.coordinator
            await coordinator.async_request_refresh()

        _LOGGER.debug("Restored all events for entry %s", entry_id)

    hass.services.async_register(
        DOMAIN,
        SERVICE_DISMISS_EVENT,
        async_dismiss_event,
        schema=SERVICE_DISMISS_EVENT_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESTORE_EVENT,
        async_restore_event,
        schema=SERVICE_RESTORE_EVENT_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESTORE_ALL_EVENTS,
        async_restore_all_events,
        schema=SERVICE_RESTORE_ALL_EVENTS_SCHEMA,
    )


async def async_setup_entry(hass: HomeAssistant, entry: TrafikinfoConfigEntry) -> bool:
    """Set up Trafikinfo SE from a config entry."""
    coordinator = TrafikinfoCoordinator(hass, entry)
    try:
        start = monotonic()
        _LOGGER.debug(
            "Starting coordinator first refresh (entry_id=%s, name=%s)",
            entry.entry_id,
            entry.title,
        )
        await coordinator.async_config_entry_first_refresh()
        _LOGGER.debug(
            "Coordinator first refresh done in %.3fs (entry_id=%s)",
            monotonic() - start,
            entry.entry_id,
        )
    except Exception as ex:
        _LOGGER.debug(
            "Coordinator first refresh failed after %.3fs (entry_id=%s): %s",
            monotonic() - start,
            entry.entry_id,
            ex,
        )
        raise ConfigEntryNotReady from ex

    entry.runtime_data = TrafikinfoRuntimeData(coordinator=coordinator)

    async def _options_updated(hass: HomeAssistant, updated_entry: ConfigEntry) -> None:
        # Options can affect entity creation (enabled message types), so reload entry.
        await hass.config_entries.async_reload(updated_entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TrafikinfoConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries."""
    if entry.version >= 5:
        return True

    _LOGGER.debug("Migrating config entry %s from version %s", entry.entry_id, entry.version)

    new_data = dict(entry.data)
    new_options = dict(entry.options)

    if entry.version < 2:
        # v2: Remove the "Färjor" sensor/category (exists natively in HA) and clean up
        # any stale options/data pointing to it.
        def _strip_farjor(val: object) -> list[str] | None:
            if not isinstance(val, list):
                return None
            out = [x for x in val if isinstance(x, str) and x != "Färjor"]
            return out

        data_types = _strip_farjor(new_data.get(CONF_MESSAGE_TYPES))
        if data_types is not None:
            new_data[CONF_MESSAGE_TYPES] = data_types or list(DEFAULT_MESSAGE_TYPES)

        opt_types = _strip_farjor(new_options.get(CONF_MESSAGE_TYPES))
        if opt_types is not None:
            new_options[CONF_MESSAGE_TYPES] = opt_types or list(DEFAULT_MESSAGE_TYPES)

        # Remove the old entity from the entity registry so it doesn't linger as an orphan.
        # Unique id format (see sensor.py): "{entry_id}_message_type_{slugify(message_type)}"
        target_unique_id = f"{entry.entry_id}_message_type_farjor"
        ent_reg = er.async_get(hass)
        for ent in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
            if ent.unique_id == target_unique_id:
                ent_reg.async_remove(ent.entity_id)

    if entry.version < 3:
        # v3: Remove deprecated option; we always use MDI icons as the primary display.
        new_data.pop("use_entity_pictures", None)
        new_options.pop("use_entity_pictures", None)

    if entry.version < 4:
        # v4: Rename entities to sensor.trafikinfo_se_<message_type> where safe.
        ent_reg = er.async_get(hass)

        display_name_map = {
            "Restriktion": "Restriktioner",
        }

        def _internal_type_from_unique_id(unique_id: str) -> str | None:
            prefix = f"{entry.entry_id}_message_type_"
            if not unique_id.startswith(prefix):
                return None
            slug = unique_id[len(prefix) :]
            for t in DEFAULT_MESSAGE_TYPES:
                if slugify(t) == slug:
                    return t
            return None

        for ent in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
            internal = _internal_type_from_unique_id(ent.unique_id)
            if not internal:
                continue
            display = display_name_map.get(internal, internal)

            desired_entity_id = f"sensor.{DOMAIN}_{slugify(display)}"
            if ent.entity_id == desired_entity_id:
                continue

            # Only rename if it looks like the entity id was auto-generated previously.
            possible_old_ids = {
                f"sensor.{slugify(internal)}",
                f"sensor.{slugify(display)}",
            }
            if ent.entity_id not in possible_old_ids:
                continue

            # Don't rename into an existing entity id (avoid collisions).
            if ent_reg.async_get(desired_entity_id) is not None:
                continue

            try:
                ent_reg.async_update_entity(ent.entity_id, new_entity_id=desired_entity_id)
            except Exception as err:
                _LOGGER.debug(
                    "Failed renaming %s -> %s: %s",
                    ent.entity_id,
                    desired_entity_id,
                    err,
                )

    if entry.version < 5:
        # v5: Introduce filter_mode + counties, keep backward compatibility.
        # Older entries used coordinate+radius only.
        from .const import (
            CONF_COUNTIES,
            CONF_FILTER_MODE,
            COUNTY_ALL,
            DEFAULT_FILTER_MODE,
            FILTER_MODE_COORDINATE,
            FILTER_MODE_COUNTY,
        )

        mode = str(new_options.get(CONF_FILTER_MODE, new_data.get(CONF_FILTER_MODE, DEFAULT_FILTER_MODE)))
        if mode == "sweden":
            # Previously experimental: Sweden-wide mode; map to county mode with 'all'
            new_data[CONF_FILTER_MODE] = FILTER_MODE_COUNTY
            new_data[CONF_COUNTIES] = [COUNTY_ALL]
        elif mode in (FILTER_MODE_COORDINATE, FILTER_MODE_COUNTY):
            new_data.setdefault(CONF_FILTER_MODE, mode)
        else:
            new_data.setdefault(CONF_FILTER_MODE, FILTER_MODE_COORDINATE)

        # If county mode is selected but no counties are set, default to Sweden-wide.
        if new_data.get(CONF_FILTER_MODE) == FILTER_MODE_COUNTY:
            counties = new_options.get(CONF_COUNTIES, new_data.get(CONF_COUNTIES))
            if not isinstance(counties, list) or not counties:
                new_data[CONF_COUNTIES] = [COUNTY_ALL]

    hass.config_entries.async_update_entry(entry, data=new_data, options=new_options, version=5)
    _LOGGER.debug("Migration to version 5 successful for %s", entry.entry_id)
    return True


