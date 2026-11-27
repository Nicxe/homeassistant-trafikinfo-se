"""Verify dashboard card installation, resource migration and bundled features."""

import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from homeassistant.components.lovelace.const import CONF_RESOURCE_TYPE_WS, LOVELACE_DATA
from homeassistant.components.lovelace.dashboard import LovelaceStorage
from homeassistant.components.lovelace.resources import (
    ResourceStorageCollection,
    ResourceYAMLCollection,
)
from homeassistant.const import EVENT_COMPONENT_LOADED
import pytest

from custom_components.trafikinfo_se import async_setup, frontend

CARD_FILENAME = "trafikinfo-se-alert-card.js"
CARD_URL = "/local/trafikinfo_se/trafikinfo-se-alert-card.js"
OLD_LOCAL_URL = "/local/trafikinfo-se-alert-card.js"
OLD_STATIC_URL = "/trafikinfo_se-static/trafikinfo-se-alert-card.js"
BUNDLED_CARD = Path(__file__).parents[1] / "www" / CARD_FILENAME


@pytest.fixture
def www(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    return tmp_path / "www"


@pytest.fixture
def resources(hass, www):
    collection = ResourceStorageCollection(hass, LovelaceStorage(hass, None))
    hass.data[LOVELACE_DATA] = SimpleNamespace(resources=collection)
    return collection


def assert_card_resource(item):
    url = urlsplit(item["url"])
    assert url.path == CARD_URL
    assert parse_qs(url.query).get("v")
    assert item["type"] == "module"


async def test_new_install_places_card_in_icon_cache_parent(hass, www, resources):
    assert await async_setup(hass, {})

    target = www / "trafikinfo_se"
    assert set(www.iterdir()) == {target}
    assert (target / CARD_FILENAME).read_bytes() == BUNDLED_CARD.read_bytes()
    (item,) = resources.async_items()
    assert_card_resource(item)

    assert await async_setup(hass, {})
    assert resources.async_items() == [item]


async def test_new_bundle_refreshes_installed_module_and_existing_resource(
    hass, www, resources, monkeypatch
):
    assert await async_setup(hass, {})
    (previous,) = resources.async_items()

    new_source = www.parent / "updated-card.js"
    new_source.write_bytes(b"export const version = 2;")
    new_mtime = int(BUNDLED_CARD.stat().st_mtime) + 60
    os.utime(new_source, (new_mtime, new_mtime))
    monkeypatch.setattr(frontend, "_card_file_path", lambda: new_source)

    assert await async_setup(hass, {})

    (current,) = resources.async_items()
    assert current["id"] == previous["id"]
    assert current["url"] != previous["url"]
    assert_card_resource(current)
    assert (
        www / "trafikinfo_se" / CARD_FILENAME
    ).read_bytes() == new_source.read_bytes()


@pytest.mark.parametrize("old_url", [OLD_LOCAL_URL, OLD_STATIC_URL])
async def test_upgrade_preserves_resource_id_and_icon_cache(
    hass, www, resources, old_url
):
    previous = await resources.async_create_item(
        {"url": f"{old_url}?v=old#card", CONF_RESOURCE_TYPE_WS: "module"}
    )
    icons = www / "trafikinfo_se" / "icons"
    icons.mkdir(parents=True)
    cached_icon = icons / "roadAccident.png"
    cached_icon.write_bytes(b"existing icon")
    root_card = www / CARD_FILENAME
    root_card.write_bytes(b"manually installed card")

    assert await async_setup(hass, {})

    (card,) = resources.async_items()
    assert card["id"] == previous["id"]
    assert_card_resource(card)
    assert cached_icon.read_bytes() == b"existing icon"
    assert root_card.read_bytes() == b"manually installed card"
    assert (icons.parent / CARD_FILENAME).read_bytes() == BUNDLED_CARD.read_bytes()


async def test_setup_keeps_new_resource_and_removes_only_known_duplicates(
    hass, resources
):
    unrelated = await resources.async_create_item(
        {"url": f"/local/custom/{CARD_FILENAME}?v=abc", CONF_RESOURCE_TYPE_WS: "module"}
    )
    for url in (OLD_STATIC_URL, OLD_LOCAL_URL):
        await resources.async_create_item({"url": url, CONF_RESOURCE_TYPE_WS: "module"})
    preferred = await resources.async_create_item(
        {"url": f"{CARD_URL}?v=old", CONF_RESOURCE_TYPE_WS: "module"}
    )

    assert await async_setup(hass, {})

    items = {item["id"]: item for item in resources.async_items()}
    assert items.keys() == {unrelated["id"], preferred["id"]}
    assert items[unrelated["id"]] == unrelated
    assert_card_resource(items[preferred["id"]])


async def test_failed_install_keeps_old_resource_until_retry(hass, www, resources):
    previous = await resources.async_create_item(
        {"url": f"{OLD_LOCAL_URL}?v=old", CONF_RESOURCE_TYPE_WS: "module"}
    )
    blocked_card = www / "trafikinfo_se" / CARD_FILENAME
    blocked_card.mkdir(parents=True)
    root_card = www / CARD_FILENAME
    root_card.write_bytes(b"old working card")

    assert await async_setup(hass, {})
    assert resources.async_items() == [previous]
    assert root_card.read_bytes() == b"old working card"

    blocked_card.rmdir()
    assert await async_setup(hass, {})
    assert blocked_card.read_bytes() == BUNDLED_CARD.read_bytes()
    (card,) = resources.async_items()
    assert previous["id"] == card["id"]
    assert_card_resource(card)


async def test_late_lovelace_setup_registers_one_resource(hass, www):
    assert await async_setup(hass, {})
    assert (www / "trafikinfo_se" / CARD_FILENAME).is_file()

    collection = ResourceStorageCollection(hass, LovelaceStorage(hass, None))
    hass.data[LOVELACE_DATA] = SimpleNamespace(resources=collection)
    for component in ("lovelace", "frontend"):
        hass.bus.async_fire(EVENT_COMPONENT_LOADED, {"component": component})
    await hass.async_block_till_done()

    (item,) = collection.async_items()
    assert_card_resource(item)


async def test_yaml_resources_remain_user_managed(hass, www):
    item = {"url": OLD_LOCAL_URL, "type": "module"}
    collection = ResourceYAMLCollection([dict(item)])
    hass.data[LOVELACE_DATA] = SimpleNamespace(resources=collection)

    assert await async_setup(hass, {})

    assert collection.async_items() == [item]
    assert (
        www / "trafikinfo_se" / CARD_FILENAME
    ).read_bytes() == BUNDLED_CARD.read_bytes()


def test_bundled_card_registers_route_card() -> None:
    card_text = BUNDLED_CARD.read_text(encoding="utf-8")

    assert "trafikinfo-se-route-card" in card_text
    assert "trafikinfo-se-route-card-editor" in card_text


def test_bundled_card_uses_policy_compliant_osm_tiles() -> None:
    card_text = BUNDLED_CARD.read_text(encoding="utf-8")

    assert "https://tile.openstreetmap.org/{z}/{x}/{y}.png" in card_text
    assert "{s}.tile.openstreetmap.org" not in card_text
    assert "referrerPolicy: MAP_TILE_REFERRER_POLICY" in card_text
    assert "attributionControl: true" in card_text
    assert "https://www.openstreetmap.org/copyright" in card_text


def test_bundled_card_validates_custom_tile_provider_config() -> None:
    card_text = BUNDLED_CARD.read_text(encoding="utf-8")

    assert "Custom map tile URL must include {z}, {x}, and {y}." in card_text
    assert "Custom map tile URL must use HTTPS or be same-origin." in card_text
    assert "Custom map tile attribution is required." in card_text
    assert "Map tile max zoom must be an integer between 0 and" in card_text
    assert card_text.count("normalizeMapTileConfig(normalized);") == 3


def test_bundled_card_editors_expose_tile_provider_fields() -> None:
    card_text = BUNDLED_CARD.read_text(encoding="utf-8")

    assert card_text.count("name: 'map_tile_url'") == 3
    assert card_text.count("name: 'map_tile_attribution'") == 3
    assert card_text.count("name: 'map_tile_max_zoom'") == 3


def test_bundled_card_editor_documents_road_filter_matching() -> None:
    card_text = BUNDLED_CARD.read_text(encoding="utf-8")

    label = (
        "Filter roads (exact numbers/names; 71* for prefixes; "
        "comma/semicolon-separated)"
    )
    assert card_text.count(label) == 2
