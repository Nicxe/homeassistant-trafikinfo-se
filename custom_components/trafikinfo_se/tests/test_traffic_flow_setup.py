"""Verify users can inspect a measurement location before saving it."""

from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResultType, InvalidData
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.trafikinfo_se.const import (
    CONF_API_KEY,
    CONF_ENTRY_KIND,
    CONF_FILTER_MODE,
    CONF_LOCATION,
    CONF_RADIUS_KM,
    CONF_SORT_LOCATION,
    CONF_TRAFFIC_FLOW_COUNTY,
    CONF_TRAFFIC_FLOW_SITE_IDS,
    CONF_TRAFFIC_FLOW_SITE_LATITUDE,
    CONF_TRAFFIC_FLOW_SITE_LONGITUDE,
    DOMAIN,
    ENTRY_KIND_TRAFFIC_FLOW,
    FILTER_MODE_COORDINATE,
    FILTER_MODE_COUNTY,
)
from custom_components.trafikinfo_se.tests.test_traffic_flow import TRAFFIC_FLOW_XML
from custom_components.trafikinfo_se.traffic_flow import (
    group_traffic_flow_sites,
    parse_traffic_flow_response,
)


@pytest.mark.parametrize("reconfigure", [False, True])
@pytest.mark.parametrize("mode", [FILTER_MODE_COORDINATE, FILTER_MODE_COUNTY])
async def test_location_preview_before_saving(
    hass, enable_custom_integrations, reconfigure, mode
):
    """Preview/back must not save, and confirming must save the inspected site."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Existing flow",
        version=8,
        data={
            CONF_API_KEY: "test-key",
            CONF_ENTRY_KIND: ENTRY_KIND_TRAFFIC_FLOW,
            CONF_TRAFFIC_FLOW_SITE_IDS: ["old-site"],
            CONF_TRAFFIC_FLOW_SITE_LATITUDE: 57.8,
            CONF_TRAFFIC_FLOW_SITE_LONGITUDE: 12.1,
        },
    )
    entry.add_to_hass(hass)
    original_data = dict(entry.data)
    sites = group_traffic_flow_sites(
        parse_traffic_flow_response(TRAFFIC_FLOW_XML).measurements,
        origin_latitude=57.8,
        origin_longitude=12.1,
    )
    sites.append(replace(sites[0], site_ids=("2001",), latitude=58.1, longitude=12.2))
    prefix = "reconfigure_" if reconfigure else ""

    with (
        patch(
            "custom_components.trafikinfo_se.config_flow.async_fetch_traffic_flow_sites",
            new_callable=AsyncMock,
            return_value=sites,
        ) as discovery,
        patch("custom_components.trafikinfo_se.async_setup_entry", return_value=True),
        patch.object(hass.config_entries, "async_reload", return_value=True) as reload,
    ):
        context = {"source": config_entries.SOURCE_USER}
        if reconfigure:
            context = {
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": entry.entry_id,
            }
        result = await hass.config_entries.flow.async_init(DOMAIN, context=context)
        flow_id = result["flow_id"]

        async def submit(data):
            return await hass.config_entries.flow.async_configure(flow_id, data)

        if not reconfigure:
            result = await submit({CONF_ENTRY_KIND: ENTRY_KIND_TRAFFIC_FLOW})
        assert result["step_id"] == f"{prefix}traffic_flow_scope"
        await submit({CONF_FILTER_MODE: mode})
        location = {"latitude": 57.8, "longitude": 12.1}
        result = await submit(
            {CONF_LOCATION: location, CONF_RADIUS_KM: 25}
            if mode == FILTER_MODE_COORDINATE
            else {CONF_SORT_LOCATION: location, CONF_TRAFFIC_FLOW_COUNTY: "14"}
        )
        assert result["step_id"] == f"{prefix}traffic_flow_site"
        # The link must be supplied by the flow, not embedded in translations.
        map_url = "https://vtf.trafikverket.se/SeTrafikinformation"
        assert result["description_placeholders"]["trafikverket_map_url"] == map_url
        integration_path = Path(__file__).resolve().parents[1]
        for filename in (
            "strings.json",
            "translations/en.json",
            "translations/sv.json",
        ):
            translations = json.loads((integration_path / filename).read_text())
            description = translations["config"]["step"][result["step_id"]][
                "description"
            ]
            assert "https://" not in description
            assert f"]({map_url})" in description.format(
                **result["description_placeholders"]
            )
        # A stale or invalid detector ID cannot proceed to confirmation.
        with pytest.raises(InvalidData):
            await submit({CONF_TRAFFIC_FLOW_SITE_IDS: "missing"})

        result = await submit(
            {CONF_TRAFFIC_FLOW_SITE_IDS: sites[0].site_key, CONF_NAME: "My flow"}
        )
        assert result["type"] == FlowResultType.MENU
        assert result["step_id"] == "traffic_flow_confirm"
        placeholders = result["description_placeholders"]
        assert placeholders["latitude"] == "57.70000"
        assert placeholders["longitude"] == "11.97004"
        assert "mlat=57.70000&mlon=11.97004" in placeholders["map_url"]
        assert "test-key" not in str(placeholders)
        assert dict(entry.data) == original_data
        reload.assert_not_called()
        assert len(hass.config_entries.async_entries(DOMAIN)) == 1

        result = await submit({"next_step_id": f"{prefix}traffic_flow_site"})
        assert result["description_placeholders"]["trafikverket_map_url"] == map_url
        defaults = result["data_schema"]({})
        assert defaults[CONF_TRAFFIC_FLOW_SITE_IDS] == sites[0].site_key
        assert defaults[CONF_NAME] == "My flow"

        result = await submit(
            {CONF_TRAFFIC_FLOW_SITE_IDS: "2001", CONF_NAME: "Replacement"}
        )
        assert result["description_placeholders"]["latitude"] == "58.10000"
        assert result["description_placeholders"]["longitude"] == "12.20000"
        result = await submit({"next_step_id": f"{prefix}traffic_flow_save"})
        if reconfigure:
            assert result["type"] == FlowResultType.ABORT
            assert result["reason"] == "reconfigured_successful"
            saved = entry
            reload.assert_called_once_with(entry.entry_id)
        else:
            assert result["step_id"] == "reload_notice"
            result = await submit({})
            assert result["type"] == FlowResultType.CREATE_ENTRY
            saved = result["result"]
        assert saved.title == "Replacement"
        assert saved.data[CONF_TRAFFIC_FLOW_SITE_IDS] == ["2001"]
        assert saved.data[CONF_TRAFFIC_FLOW_SITE_LATITUDE] == 58.1
        assert saved.data[CONF_TRAFFIC_FLOW_SITE_LONGITUDE] == 12.2
        assert saved.data[CONF_LOCATION] == location
        assert saved.data[CONF_API_KEY] == "test-key"
        discovery.assert_awaited_once()
        await hass.async_block_till_done()
