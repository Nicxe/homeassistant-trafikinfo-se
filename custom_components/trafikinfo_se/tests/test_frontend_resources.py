from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.const import CONF_ID, CONF_TYPE
import pytest

from custom_components.trafikinfo_se import frontend
from custom_components.trafikinfo_se.const import (
    CARD_CANONICAL_BASE_URL,
    CARD_LEGACY_BASE_URL,
    FRONTEND_DATA_KEY,
)


class _FakeResources:
    def __init__(self, items: list[dict] | None = None) -> None:
        self._items = list(items or [])
        self.loaded = False
        self.create_calls = 0
        self.update_calls = 0

    async def async_load(self) -> None:
        self.loaded = True

    def async_items(self) -> list[dict]:
        return list(self._items)

    async def async_create_item(self, data: dict) -> dict:
        self.create_calls += 1
        item = {
            CONF_ID: f"generated-{self.create_calls}",
            "url": data["url"],
            CONF_TYPE: data.get("res_type", "module"),
        }
        self._items.append(item)
        return item

    async def async_update_item(self, item_id: str, updates: dict) -> dict:
        self.update_calls += 1
        for item in self._items:
            if item[CONF_ID] == item_id:
                item["url"] = updates["url"]
                if "res_type" in updates:
                    item[CONF_TYPE] = updates["res_type"]
                return item
        raise KeyError(item_id)


@pytest.fixture
def hass():
    return SimpleNamespace(data={})


@pytest.mark.asyncio
async def test_ensure_resource_creates_when_missing(hass, monkeypatch) -> None:
    resources = _FakeResources()
    hass.data[LOVELACE_DATA] = SimpleNamespace(resources=resources)

    async def _fake_cache_key(_hass):
        return "0.0.0-123"

    monkeypatch.setattr(frontend, "_cache_key_for_dev", _fake_cache_key)

    ok = await frontend._async_ensure_card_resource(hass)

    assert ok is True
    assert resources.create_calls == 1
    created = resources.async_items()[0]
    assert created[CONF_TYPE] == "module"
    assert created["url"] == f"{CARD_LEGACY_BASE_URL}?v=0.0.0-123"


@pytest.mark.asyncio
async def test_ensure_resource_updates_existing_canonical(hass, monkeypatch) -> None:
    resources = _FakeResources(
        [
            {
                CONF_ID: "abc",
                CONF_TYPE: "module",
                "url": f"{CARD_CANONICAL_BASE_URL}?v=old",
            }
        ]
    )
    hass.data[LOVELACE_DATA] = SimpleNamespace(resources=resources)

    async def _fake_cache_key(_hass):
        return "0.0.0-456"

    monkeypatch.setattr(frontend, "_cache_key_for_dev", _fake_cache_key)

    ok = await frontend._async_ensure_card_resource(hass)

    assert ok is True
    assert resources.update_calls == 1
    assert resources.async_items()[0]["url"] == f"{CARD_LEGACY_BASE_URL}?v=0.0.0-456"


@pytest.mark.asyncio
async def test_ensure_resource_prefers_existing_local_over_canonical(
    hass, monkeypatch
) -> None:
    resources = _FakeResources(
        [
            {CONF_ID: "local", CONF_TYPE: "module", "url": CARD_LEGACY_BASE_URL},
            {CONF_ID: "canonical", CONF_TYPE: "module", "url": CARD_CANONICAL_BASE_URL},
        ]
    )
    hass.data[LOVELACE_DATA] = SimpleNamespace(resources=resources)

    async def _fake_cache_key(_hass):
        return "0.0.0-789"

    monkeypatch.setattr(frontend, "_cache_key_for_dev", _fake_cache_key)

    ok = await frontend._async_ensure_card_resource(hass)

    assert ok is True
    assert resources.update_calls == 1
    items = {item[CONF_ID]: item for item in resources.async_items()}
    assert items["local"]["url"] == f"{CARD_LEGACY_BASE_URL}?v=0.0.0-789"
    assert items["canonical"]["url"] == CARD_CANONICAL_BASE_URL


@pytest.mark.asyncio
async def test_ensure_resource_is_idempotent(hass, monkeypatch) -> None:
    resources = _FakeResources(
        [
            {
                CONF_ID: "abc",
                CONF_TYPE: "module",
                "url": f"{CARD_LEGACY_BASE_URL}?v=stable",
            }
        ]
    )
    hass.data[LOVELACE_DATA] = SimpleNamespace(resources=resources)

    async def _fake_cache_key(_hass):
        return "stable"

    monkeypatch.setattr(frontend, "_cache_key_for_dev", _fake_cache_key)

    ok = await frontend._async_ensure_card_resource(hass)

    assert ok is True
    assert resources.create_calls == 0
    assert resources.update_calls == 0


@pytest.mark.asyncio
async def test_ensure_resource_migrates_canonical_to_local(hass, monkeypatch) -> None:
    resources = _FakeResources(
        [
            {
                CONF_ID: "canonical",
                CONF_TYPE: "module",
                "url": f"{CARD_CANONICAL_BASE_URL}?v=old",
            }
        ]
    )
    hass.data[LOVELACE_DATA] = SimpleNamespace(resources=resources)

    async def _fake_cache_key(_hass):
        return "0.0.0-999"

    monkeypatch.setattr(frontend, "_cache_key_for_dev", _fake_cache_key)

    ok = await frontend._async_ensure_card_resource(hass)

    assert ok is True
    assert resources.update_calls == 1
    assert resources.async_items()[0]["url"] == f"{CARD_LEGACY_BASE_URL}?v=0.0.0-999"


@pytest.mark.asyncio
async def test_ensure_resource_falls_back_without_lovelace(hass, monkeypatch) -> None:
    async def _fake_cache_key(_hass):
        return "fallback"

    monkeypatch.setattr(frontend, "_cache_key_for_dev", _fake_cache_key)

    ok = await frontend._async_ensure_card_resource(hass)

    assert ok is False


@pytest.mark.asyncio
async def test_setup_frontend_refreshes_card_after_integration_reload(
    hass, monkeypatch
) -> None:
    hass.data[FRONTEND_DATA_KEY] = {"setup_done": True}
    calls: list[str] = []

    async def _fake_cache_key(_hass):
        return "0.0.0-new"

    async def _fake_sync(_hass):
        calls.append("sync")

    async def _fake_ensure(_hass):
        calls.append("resource")
        return True

    monkeypatch.setattr(frontend, "_cache_key_for_dev", _fake_cache_key)
    monkeypatch.setattr(frontend, "_async_sync_card_to_local_www", _fake_sync)
    monkeypatch.setattr(frontend, "_async_ensure_card_resource", _fake_ensure)

    await frontend.async_setup_frontend(hass)

    assert calls == ["sync", "resource"]
    assert hass.data[FRONTEND_DATA_KEY]["cache_key"] == "0.0.0-new"


def test_bundled_card_registers_route_card() -> None:
    card_path = Path(frontend._card_file_path())
    card_text = card_path.read_text(encoding="utf-8")

    assert "trafikinfo-se-route-card" in card_text
    assert "trafikinfo-se-route-card-editor" in card_text


def test_bundled_card_uses_policy_compliant_osm_tiles() -> None:
    card_path = Path(frontend._card_file_path())
    card_text = card_path.read_text(encoding="utf-8")

    assert "https://tile.openstreetmap.org/{z}/{x}/{y}.png" in card_text
    assert "{s}.tile.openstreetmap.org" not in card_text
    assert "referrerPolicy: MAP_TILE_REFERRER_POLICY" in card_text
    assert "attributionControl: true" in card_text
    assert "https://www.openstreetmap.org/copyright" in card_text


def test_bundled_card_validates_custom_tile_provider_config() -> None:
    card_path = Path(frontend._card_file_path())
    card_text = card_path.read_text(encoding="utf-8")

    assert "Custom map tile URL must include {z}, {x}, and {y}." in card_text
    assert "Custom map tile URL must use HTTPS or be same-origin." in card_text
    assert "Custom map tile attribution is required." in card_text
    assert "Map tile max zoom must be an integer between 0 and" in card_text
    assert card_text.count("normalizeMapTileConfig(normalized);") == 2


def test_bundled_card_editors_expose_tile_provider_fields() -> None:
    card_path = Path(frontend._card_file_path())
    card_text = card_path.read_text(encoding="utf-8")

    assert card_text.count("name: 'map_tile_url'") == 2
    assert card_text.count("name: 'map_tile_attribution'") == 2
    assert card_text.count("name: 'map_tile_max_zoom'") == 2
