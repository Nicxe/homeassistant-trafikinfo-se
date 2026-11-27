"""Frontend resource management for Trafikinfo SE card."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from homeassistant.components.lovelace.const import (
    CONF_RESOURCE_TYPE_WS,
    CONF_URL,
    LOVELACE_DATA,
)
from homeassistant.components.lovelace.resources import ResourceYAMLCollection
from homeassistant.const import CONF_ID, CONF_TYPE, EVENT_COMPONENT_LOADED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.util.file import WriteError, write_utf8_file

from .const import (
    CARD_BASE_URL,
    CARD_FILENAME,
    CARD_RESOURCE_URLS,
    CARD_WWW_DIR,
    DOMAIN,
    FRONTEND_DATA_COMPONENT_LISTENER,
    FRONTEND_DATA_KEY,
)

_LOGGER = logging.getLogger(__name__)


def _card_file_path() -> Path:
    """Return absolute path to bundled card file."""
    return Path(__file__).resolve().parent / CARD_WWW_DIR / CARD_FILENAME


def _read_manifest_version() -> str:
    """Read integration version from manifest.json."""
    manifest_path = Path(__file__).resolve().parent / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "0.0.0"
    return str(manifest.get("version", "0.0.0"))


def _card_mtime() -> int:
    """Read card mtime."""
    card_path = _card_file_path()
    try:
        return int(card_path.stat().st_mtime)
    except OSError:
        return 0


def _sync_card(target_dir: Path) -> None:
    """Install the dashboard module alongside its cached traffic icons."""
    content = _card_file_path().read_bytes()
    target = target_dir / CARD_FILENAME
    if target.is_file() and target.read_bytes() == content:
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    write_utf8_file(str(target), content, mode="wb")


async def _cache_key_for_dev(hass: HomeAssistant) -> str:
    """Build cache key from manifest version and card mtime."""
    version_task = hass.async_add_executor_job(_read_manifest_version)
    mtime_task = hass.async_add_executor_job(_card_mtime)
    version, mtime = await asyncio.gather(version_task, mtime_task)
    return f"{version}-{mtime}"


def _url_base(url: str) -> str:
    """Return URL without query/fragment to allow stable comparisons."""
    return url.partition("?")[0].partition("#")[0]


async def _async_get_lovelace_resources(hass: HomeAssistant):
    """Return Lovelace resource collection or None if unavailable."""
    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None:
        return None

    resources = getattr(lovelace_data, "resources", None)
    if resources is None:
        return None

    if (
        hasattr(resources, "loaded")
        and not resources.loaded
        and hasattr(resources, "async_load")
    ):
        await resources.async_load()
        resources.loaded = True

    return resources


async def _async_ensure_card_resource(hass: HomeAssistant, cache_key: str) -> bool:
    """Migrate the managed Lovelace resource after the module is installed."""
    desired_url = f"{CARD_BASE_URL}?{urlencode({'v': cache_key})}"

    try:
        resources = await _async_get_lovelace_resources(hass)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Unable to load Lovelace resources: %s", err)
        resources = None

    if resources is None:
        _LOGGER.debug(
            "Lovelace resources API unavailable, skipping card resource sync for %s",
            desired_url,
        )
        return False

    if isinstance(resources, ResourceYAMLCollection):
        return True

    updates = {CONF_URL: desired_url, CONF_RESOURCE_TYPE_WS: "module"}
    try:
        matches = [
            item
            for item in resources.async_items()
            if isinstance(url := item.get(CONF_URL), str)
            and _url_base(url) in CARD_RESOURCE_URLS
        ]
        if not matches:
            await resources.async_create_item(updates)
            return True

        matches.sort(
            key=lambda item: CARD_RESOURCE_URLS.index(_url_base(item[CONF_URL]))
        )
        target, *duplicates = matches
        if target[CONF_URL] != desired_url or target.get(CONF_TYPE) != "module":
            await resources.async_update_item(target[CONF_ID], updates)
        for duplicate in duplicates:
            await resources.async_delete_item(duplicate[CONF_ID])
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Unable to update dashboard card resource: %s", err)
        return False

    return True


def _async_component_loaded_listener(hass: HomeAssistant) -> Callable[[], None]:
    """Create component-loaded listener for late Lovelace startup."""

    @callback
    def _handle_component_loaded(event: Event) -> None:
        if event.data.get("component") not in ("lovelace", "frontend"):
            return
        hass.async_create_task(async_setup_frontend(hass, refresh_resource=True))

    return hass.bus.async_listen(EVENT_COMPONENT_LOADED, _handle_component_loaded)


async def async_setup_frontend(
    hass: HomeAssistant, *, refresh_resource: bool = False
) -> None:
    """Install the card before creating or migrating its dashboard resource."""
    state: dict[str, Any] = hass.data.setdefault(FRONTEND_DATA_KEY, {})
    async with state.setdefault("lock", asyncio.Lock()):
        if FRONTEND_DATA_COMPONENT_LISTENER not in hass.data:
            hass.data[FRONTEND_DATA_COMPONENT_LISTENER] = (
                _async_component_loaded_listener(hass)
            )

        cache_key = await _cache_key_for_dev(hass)
        if state.get("cache_key") != cache_key:
            try:
                await hass.async_add_executor_job(
                    _sync_card, Path(hass.config.path("www", DOMAIN))
                )
            except (OSError, WriteError) as err:
                _LOGGER.warning("Unable to install dashboard card: %s", err)
                return
        elif not refresh_resource:
            return
        if await _async_ensure_card_resource(hass, cache_key):
            state["cache_key"] = cache_key
