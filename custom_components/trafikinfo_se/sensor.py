"""Sensor platform for Trafikinfo SE."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import (
    ATTRIBUTION,
    CONF_MESSAGE_TYPES,
    DEFAULT_MESSAGE_TYPES,
    DOMAIN,
)
from .coordinator import TrafikinfoCoordinator, TrafikinfoData

MESSAGE_TYPES: list[str] = [
    "Viktig trafikinformation",
    "Hinder",
    "Olycka",
    "Restriktion",
    "Trafikmeddelande",
    "Vägarbete",
]

# Keep MESSAGE_TYPES in sync with DEFAULT_MESSAGE_TYPES (used for UI options defaults).
# If they diverge, prefer DEFAULT_MESSAGE_TYPES.
if MESSAGE_TYPES != DEFAULT_MESSAGE_TYPES:
    MESSAGE_TYPES = list(DEFAULT_MESSAGE_TYPES)

# Map known MessageTypeValue (code values) into our 7 stable categories.
# Note: MessageType is typically Swedish category text (e.g. "Olycka"),
# while MessageTypeValue is a more fine-grained English code (e.g. "Accident").
MESSAGE_TYPE_VALUE_TO_CATEGORY: dict[str, str] = {
    # Olycka
    "Accident": "Olycka",
    # Hinder
    "GeneralObstruction": "Hinder",
    # Vägarbete
    "MaintenanceWorks": "Vägarbete",
    # Trafikmeddelande (many subtypes)
    "VehicleObstruction": "Trafikmeddelande",
    "AnimalPresenceObstruction": "Trafikmeddelande",
    "RoadsideAssistance": "Trafikmeddelande",
    "SpeedManagement": "Trafikmeddelande",
    "ReroutingManagement": "Trafikmeddelande",
    "EnvironmentalObstruction": "Trafikmeddelande",
    "RoadOrCarriagewayOrLaneManagement": "Trafikmeddelande",
}

MESSAGE_TYPE_ICONS: dict[str, str] = {
    "Viktig trafikinformation": "mdi:alert-octagon",
    "Hinder": "mdi:alert-decagram-outline",
    "Olycka": "mdi:alert",
    "Restriktion": "mdi:road-variant",
    "Trafikmeddelande": "mdi:message-text",
    "Vägarbete": "mdi:traffic-cone",
}

MESSAGE_TYPE_COLORS: dict[str, str] = {
    "Viktig trafikinformation": "#b71c1c",
    "Hinder": "#ef6c00",
    "Olycka": "#4e342e",
    "Restriktion": "#6a1b9a",
    "Trafikmeddelande": "#2e7d32",
    "Vägarbete": "#f9a825",
}

# Category -> Trafikverket IconId (stable, from Icon dataset)
CATEGORY_ICON_ID: dict[str, str] = {
    "Olycka": "roadAccident",
    "Hinder": "trafficMessagePlanned",
    "Viktig trafikinformation": "emergencyInformation",
    "Restriktion": "trafficMessagePlanned",
}


def _svg_badge_data_uri(label: str, *, bg: str) -> str:
    """Small inline SVG badge as a data URI (works as entity_picture)."""
    label = (label or "?")[:2]
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'
        f'<circle cx="32" cy="32" r="30" fill="{bg}"/>'
        f'<text x="32" y="39" text-anchor="middle" font-size="28" '
        f'font-family="Arial, Helvetica, sans-serif" fill="#fff">{label}</text>'
        f"</svg>"
    )
    # Encode strictly to avoid broken images in some browsers/cards.
    return "data:image/svg+xml;charset=utf-8," + quote(svg, safe="")


def _fallback_picture_for_category(category: str | None) -> str:
    cat = category or "T"
    bg = MESSAGE_TYPE_COLORS.get(cat, "#616161")
    # Use a short label to keep it readable in small cards
    label_map = {
        "Viktig trafikinformation": "!",
        "Hinder": "H",
        "Olycka": "O",
        "Restriktion": "R",
        "Trafikmeddelande": "T",
        "Vägarbete": "V",
    }
    return _svg_badge_data_uri(label_map.get(cat, cat[:1]), bg=bg)


def _category_picture_url(
    coordinator: TrafikinfoCoordinator, category: str
) -> str | None:
    """Return best URL for a category picture (local cached if available)."""
    icon_id = CATEGORY_ICON_ID.get(category)
    if not icon_id:
        return None
    local = coordinator.get_local_icon_url(icon_id)
    if isinstance(local, str) and local:
        return local
    remote = coordinator.get_remote_icon_url(icon_id)
    return remote if isinstance(remote, str) and remote else None

def _category_for_event(event: Any) -> str | None:
    """Resolve one of MESSAGE_TYPES for a TrafikinfoEvent-like object."""
    # Prefer Swedish category text when it matches our known stable categories.
    msg_type = getattr(event, "message_type", None)
    if isinstance(msg_type, str) and msg_type in set(MESSAGE_TYPES):
        return msg_type

    # Map more fine-grained code values to categories.
    msg_value = getattr(event, "message_type_value", None)
    if isinstance(msg_value, str):
        mapped = MESSAGE_TYPE_VALUE_TO_CATEGORY.get(msg_value)
        if mapped:
            return mapped

    # If we still don't know: fall back to MessageType if it's set (even if unexpected),
    # otherwise keep it unclassified.
    if isinstance(msg_type, str) and msg_type.strip():
        return msg_type.strip()

    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor(s) from a config entry."""
    coordinator: TrafikinfoCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    enabled = entry.options.get(CONF_MESSAGE_TYPES, entry.data.get(CONF_MESSAGE_TYPES, DEFAULT_MESSAGE_TYPES))
    if not isinstance(enabled, list) or not enabled:
        enabled = list(DEFAULT_MESSAGE_TYPES)
    enabled_set = set(enabled)

    entities: list[SensorEntity] = []
    for msg_type in DEFAULT_MESSAGE_TYPES:
        if msg_type in enabled_set:
            entities.append(TrafikinfoMessageTypeSensor(entry, coordinator, msg_type))
    async_add_entities(entities)


class TrafikinfoMessageTypeSensor(CoordinatorEntity[TrafikinfoCoordinator], SensorEntity):
    """Sensor showing number of active traffic events for a specific MessageType."""

    # Use full friendly names directly (no device-name prefix).
    _attr_has_entity_name = False
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: TrafikinfoCoordinator,
        message_type: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._message_type = message_type
        self._attr_unique_id = f"{entry.entry_id}_message_type_{slugify(message_type)}"
        # Friendly display names (keep internal categories unchanged).
        display_name_map = {
            "Restriktion": "Restriktioner",
        }
        self._attr_name = display_name_map.get(message_type, message_type)
        self._attr_icon = MESSAGE_TYPE_ICONS.get(message_type, "mdi:traffic-cone")

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="Trafikverket",
            model="Road.TrafficInfo Situation",
        )

    def _filtered_events(self) -> list[Any]:
        data: TrafikinfoData | None = self.coordinator.data
        if not data:
            return []
        # Group into stable categories using MessageType when possible, otherwise map
        # MessageTypeValue (code values) into categories.
        out = []
        for e in data.events:
            if _category_for_event(e) == self._message_type:
                out.append(e)
        return out

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.data:
            return None
        return len(self._filtered_events())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"attribution": ATTRIBUTION}
        data: TrafikinfoData | None = self.coordinator.data
        if not data:
            return attrs

        filtered = self._filtered_events()
        max_items = max(0, int(self.coordinator.max_items))
        if max_items == 0:
            events = []
        else:
            events = [e.as_dict() for e in filtered[:max_items]]

        # Expose a simple icon URL surface for dashboards/templates.
        # Note: we intentionally do not set the HA `entity_picture` property anymore
        # (always use MDI icon), but we keep URLs in attributes for users who want them.
        picture_url = _category_picture_url(self.coordinator, self._message_type)
        # Always expose the URL in attributes so users can use it in templates/cards.
        entity_picture_attr = picture_url

        attrs.update(
            {
                "message_type": self._message_type,
                "filter_center": {
                    "latitude": getattr(self.coordinator, "latitude", None),
                    "longitude": getattr(self.coordinator, "longitude", None),
                },
                "filter_radius_km": getattr(self.coordinator, "radius_km", None),
                "entity_picture": entity_picture_attr,
                "icon_url": picture_url,
                "events": events,
                "events_total": len(filtered),
                "max_items": max_items,
                "last_modified": data.last_modified.isoformat()
                if data.last_modified is not None
                else None,
                "last_change_id": data.last_change_id,
                "sse_url": data.sse_url,
            }
        )
        return attrs

