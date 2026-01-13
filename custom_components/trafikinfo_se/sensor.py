"""Sensor platform for Trafikinfo SE."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
from typing import Any
from urllib.parse import quote

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .__init__ import TrafikinfoConfigEntry
from .const import (
    ATTRIBUTION,
    CONF_MESSAGE_TYPES,
    DEFAULT_MESSAGE_TYPES,
    DOMAIN,
)
from .coordinator import TrafikinfoCoordinator, TrafikinfoData

_LOGGER = logging.getLogger(__name__)

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


@dataclass(frozen=True, kw_only=True)
class TrafikinfoSensorEntityDescription(SensorEntityDescription):
    """Describes Trafikinfo sensor entity."""

    message_type: str
    icon_mdi: str
    badge_color: str
    icon_id_fallback: str | None = None


SENSOR_DESCRIPTIONS: dict[str, TrafikinfoSensorEntityDescription] = {
    "Viktig trafikinformation": TrafikinfoSensorEntityDescription(
        key="viktig_trafikinformation",
        translation_key="viktig_trafikinformation",
        message_type="Viktig trafikinformation",
        icon_mdi="mdi:alert-octagon",
        badge_color="#b71c1c",
        icon_id_fallback="emergencyInformation",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "Hinder": TrafikinfoSensorEntityDescription(
        key="hinder",
        translation_key="hinder",
        message_type="Hinder",
        icon_mdi="mdi:alert-decagram-outline",
        badge_color="#ef6c00",
        icon_id_fallback="trafficMessagePlanned",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "Olycka": TrafikinfoSensorEntityDescription(
        key="olycka",
        translation_key="olycka",
        message_type="Olycka",
        icon_mdi="mdi:alert",
        badge_color="#4e342e",
        icon_id_fallback="roadAccident",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "Restriktion": TrafikinfoSensorEntityDescription(
        key="restriktion",
        translation_key="restriktion",
        message_type="Restriktion",
        icon_mdi="mdi:road-variant",
        badge_color="#6a1b9a",
        icon_id_fallback="trafficMessagePlanned",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "Trafikmeddelande": TrafikinfoSensorEntityDescription(
        key="trafikmeddelande",
        translation_key="trafikmeddelande",
        message_type="Trafikmeddelande",
        icon_mdi="mdi:message-text",
        badge_color="#2e7d32",
        icon_id_fallback=None,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "Vägarbete": TrafikinfoSensorEntityDescription(
        key="vagarbete",
        translation_key="vagarbete",
        message_type="Vägarbete",
        icon_mdi="mdi:traffic-cone",
        badge_color="#f9a825",
        icon_id_fallback=None,
        state_class=SensorStateClass.MEASUREMENT,
    ),
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
    entry: TrafikinfoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor(s) from a config entry."""
    coordinator: TrafikinfoCoordinator = entry.runtime_data.coordinator
    enabled = entry.options.get(CONF_MESSAGE_TYPES, entry.data.get(CONF_MESSAGE_TYPES, DEFAULT_MESSAGE_TYPES))
    if not isinstance(enabled, list) or not enabled:
        enabled = list(DEFAULT_MESSAGE_TYPES)
    enabled_set = set(enabled)

    entities: list[SensorEntity] = []
    for msg_type in DEFAULT_MESSAGE_TYPES:
        if msg_type in enabled_set and msg_type in SENSOR_DESCRIPTIONS:
            description = SENSOR_DESCRIPTIONS[msg_type]
            entities.append(TrafikinfoMessageTypeSensor(entry, coordinator, description))
    async_add_entities(entities)


class TrafikinfoMessageTypeSensor(CoordinatorEntity[TrafikinfoCoordinator], SensorEntity):
    """Sensor showing number of active traffic events for a specific MessageType."""

    entity_description: TrafikinfoSensorEntityDescription
    _attr_has_entity_name = True
    _EVENT_PUBLISH_TYPES = {"Hinder", "Olycka"}

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: TrafikinfoCoordinator,
        entity_description: TrafikinfoSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._entry = entry
        self._message_type = entity_description.message_type

        # Unique ID preserved for backward compatibility
        self._attr_unique_id = f"{entry.entry_id}_message_type_{slugify(self._message_type)}"
        self._attr_icon = entity_description.icon_mdi

        self._incident_bus_name: str | None = None
        self._diff_initialized: bool = False
        # incident_key -> signature (used to detect new/changed incidents)
        self._last_incident_signatures: dict[str, str] = {}
        if self._message_type in self._EVENT_PUBLISH_TYPES:
            # Per-incident event (fires once per new/changed incident)
            # - trafikinfo_se_hinder_incident
            # - trafikinfo_se_olycka_incident
            self._incident_bus_name = f"{DOMAIN}_{slugify(self._message_type)}_incident"

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

    def _incident_key(self, event: Any) -> str | None:
        """Stable key for one incident."""
        dev_id = getattr(event, "deviation_id", None)
        if isinstance(dev_id, str) and dev_id:
            return dev_id
        sit_id = getattr(event, "situation_id", None)
        if isinstance(sit_id, str) and sit_id:
            return sit_id
        # Fallback: this should be rare, but avoid crashing.
        msg = getattr(event, "message", None)
        head = getattr(event, "header", None)
        if isinstance(msg, str) and msg:
            return hashlib.sha1(f"{head}|{msg}".encode("utf-8")).hexdigest()
        return None

    def _incident_signature(self, event: Any) -> str:
        """Signature that changes when an incident changes."""
        # Prefer timestamps that usually change on updates.
        parts: list[str] = []
        for attr in ("modified_time", "version_time", "publication_time", "end_time", "start_time"):
            v = getattr(event, attr, None)
            try:
                parts.append(v.isoformat() if hasattr(v, "isoformat") else str(v))
            except Exception:
                parts.append(str(v))
        # Include key text to catch changes even if timestamps are missing.
        for attr in ("severity_code", "severity_text", "message_type", "message_type_value", "header", "message"):
            v = getattr(event, attr, None)
            parts.append(str(v) if v is not None else "")
        return "|".join(parts)

    def _incident_dict(self, event: Any) -> dict[str, Any]:
        """Convert one incident to dict including distance_km if available."""
        try:
            d = event.as_dict() if hasattr(event, "as_dict") else {}
        except Exception:
            d = {}
        dist = self.coordinator.event_distance_km(event)
        if dist is not None:
            d["distance_km"] = round(float(dist), 2)
        return d

    def _maybe_fire_event(self) -> None:
        """Publish one event per new/changed incident (hinder/olycka only)."""
        if not self._incident_bus_name:
            return
        data: TrafikinfoData | None = self.coordinator.data
        if not data:
            return

        filtered = self._filtered_events()
        cur: dict[str, str] = {}
        cur_events_by_key: dict[str, Any] = {}
        for e in filtered:
            k = self._incident_key(e)
            if not k:
                continue
            cur_events_by_key[k] = e
            cur[k] = self._incident_signature(e)

        if not self._diff_initialized:
            # Avoid startup spam: establish baseline on first publish.
            self._diff_initialized = True
            self._last_incident_signatures = cur
            return

        prev = self._last_incident_signatures
        added_or_changed: list[str] = []
        for k, sig in cur.items():
            if k not in prev or prev.get(k) != sig:
                added_or_changed.append(k)

        received_at = dt_util.utcnow().isoformat(timespec="seconds")
        # Fire one event per new/changed incident (most useful for notifications).
        for k in added_or_changed[:200]:
            e = cur_events_by_key.get(k)
            if e is None:
                continue
            payload = {
                "entry_id": self._entry.entry_id,
                "entry_title": self._entry.title,
                "entity_id": getattr(self, "entity_id", None),
                "message_type": self._message_type,
                "incident_key": k,
                "change_type": "added" if k not in prev else "updated",
                "received_at": received_at,
                "incident": self._incident_dict(e),
            }
            try:
                self.hass.bus.async_fire(self._incident_bus_name, payload)
            except Exception:
                _LOGGER.debug("Failed to publish %s incident", self._incident_bus_name)

        self._last_incident_signatures = cur

    def _handle_coordinator_update(self) -> None:
        # Fire event before writing state so listeners can react immediately to the update.
        self._maybe_fire_event()
        super()._handle_coordinator_update()

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
        sorted_events = self.coordinator.sort_events(filtered)
        max_items = max(0, int(self.coordinator.max_items))
        if max_items == 0:
            events = []
        else:
            out = []
            for e in sorted_events[:max_items]:
                d = e.as_dict()
                dist = self.coordinator.event_distance_km(e)
                if dist is not None:
                    # Rounded for readability in dashboards
                    d["distance_km"] = round(float(dist), 2)
                out.append(d)
            events = out

        # Expose a simple icon URL surface for dashboards/templates.
        # Note: we intentionally do not set the HA `entity_picture` property anymore
        # (always use MDI icon), but we keep URLs in attributes for users who want them.
        picture_url = _category_picture_url(self.coordinator, self._message_type)
        # Always expose the URL in attributes so users can use it in templates/cards.
        entity_picture_attr = picture_url

        attrs.update(
            {
                "message_type": self._message_type,
                "filter_mode": getattr(self.coordinator, "filter_mode", None),
                "filter_counties": getattr(self.coordinator, "counties", None),
                "filter_roads": getattr(self.coordinator, "filter_roads", None),
                "filter_center": {
                    "latitude": getattr(self.coordinator, "latitude", None),
                    "longitude": getattr(self.coordinator, "longitude", None),
                }
                if getattr(self.coordinator, "filter_mode", None) == "coordinate"
                else None,
                "filter_radius_km": getattr(self.coordinator, "radius_km", None)
                if getattr(self.coordinator, "filter_mode", None) == "coordinate"
                else None,
                "sort_mode": getattr(self.coordinator, "sort_mode", None),
                "sort_reference": {
                    "latitude": getattr(self.coordinator, "sort_latitude", None),
                    "longitude": getattr(self.coordinator, "sort_longitude", None),
                },
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

