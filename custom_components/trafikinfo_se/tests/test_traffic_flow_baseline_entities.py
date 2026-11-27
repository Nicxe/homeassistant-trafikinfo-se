"""Exercise dormant comparison support through config-entry lifecycle tests."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.trafikinfo_se import sensor as sensor_module
from custom_components.trafikinfo_se.const import (
    CONF_API_KEY,
    CONF_ENTRY_KIND,
    CONF_TRAFFIC_FLOW_SITE_IDS,
    CONF_TRAFFIC_FLOW_SITE_LATITUDE,
    CONF_TRAFFIC_FLOW_SITE_LONGITUDE,
    DOMAIN,
    ENTRY_KIND_TRAFFIC_FLOW,
)
from custom_components.trafikinfo_se.tests.test_traffic_flow import TRAFFIC_FLOW_XML
from custom_components.trafikinfo_se.traffic_flow import (
    TrafficFlowComparison,
    parse_traffic_flow_response,
)


@pytest.mark.parametrize("enabled", [False, True])
async def test_comparison_entities_setup_update_reload_and_unload(
    hass, enable_custom_integrations, freezer, enabled
):
    """Gate registration and attributes, preserve currents, and reuse one fetch."""
    freezer.move_to("2026-08-26T10:02:00+00:00")
    snapshot = parse_traffic_flow_response(
        TRAFFIC_FLOW_XML,
        now=datetime(2026, 8, 26, 10, 2, tzinfo=UTC),
    )
    # Synthetic normalized adapter output, not a claimed TrafficFlow 1.6 payload.
    snapshot = replace(
        snapshot,
        comparison=TrafficFlowComparison(
            status="valid",
            flow_reference=1000,
            speed_reference=80,
            flow_deviation_percent=30,
            speed_deviation_percent=-35,
            flow_deviation_absolute=300,
            speed_deviation_absolute=-28,
            matched_detector_count=3,
            expected_detector_count=3,
        ),
        total_flow_rate=1300,
        weighted_average_speed=52,
        data_quality="good",
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=8,
        title="Baseline test",
        data={
            CONF_API_KEY: "test-key",
            CONF_ENTRY_KIND: ENTRY_KIND_TRAFFIC_FLOW,
            CONF_TRAFFIC_FLOW_SITE_IDS: ["1001", "1002", "1003"],
            CONF_TRAFFIC_FLOW_SITE_LATITUDE: 57.7,
            CONF_TRAFFIC_FLOW_SITE_LONGITUDE: 11.97,
        },
    )
    entry.add_to_hass(hass)
    with (
        patch.object(sensor_module, "TRAFFIC_FLOW_BASELINE_ENABLED", enabled),
        patch("custom_components.trafikinfo_se.async_setup_frontend", new=AsyncMock()),
        patch(
            "custom_components.trafikinfo_se.traffic_flow.TrafficFlowCoordinator._async_update_data",
            new=AsyncMock(return_value=snapshot),
        ) as fetch,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        registry = er.async_get(hass)

        def states_by_key():
            prefix = f"{entry.entry_id}_traffic_flow_"
            return {
                entity.unique_id.removeprefix(prefix): hass.states.get(entity.entity_id)
                for entity in er.async_entries_for_config_entry(
                    registry, entry.entry_id
                )
            }

        states = states_by_key()
        assert len(states) == (7 if enabled else 3)
        assert states["rate"].state == "1300"
        assert states["speed"].state == "52"
        assert ("baseline_comparison" in states["rate"].attributes) is enabled
        assert fetch.await_count == 1
        if enabled:
            assert states["flow_reference"].state == "1000"
            assert states["speed_reference"].state == "80"
            assert states["flow_deviation_percent"].state == "30"
            assert states["speed_deviation_percent"].state == "-35"
            assert "state_class" not in states["speed_reference"].attributes
            assert (
                states["speed_deviation_percent"].attributes["state_class"]
                == "measurement"
            )
            assert (
                "baseline_comparison"
                in states["rate"].state_info["unrecorded_attributes"]
            )
            for key in ("flow_reference", "speed_reference"):
                assert "site_ids" not in states[key].attributes

            coordinator = entry.runtime_data.traffic_flow_coordinator
            coordinator.async_set_updated_data(
                replace(snapshot, comparison=TrafficFlowComparison(status="incomplete"))
            )
            await hass.async_block_till_done()
            states = states_by_key()
            assert states["rate"].state == "1300"
            assert states["speed"].state == "52"
            for key in (
                "flow_reference",
                "speed_reference",
                "flow_deviation_percent",
                "speed_deviation_percent",
            ):
                assert states[key].state == "unknown"
            assert (
                states["rate"].attributes["baseline_comparison"]["status"]
                == "incomplete"
            )

            coordinator.async_set_update_error(RuntimeError("Mock API unavailable"))
            await hass.async_block_till_done()
            assert all(
                state.state == "unavailable" for state in states_by_key().values()
            )

        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert fetch.await_count == 2
        assert len(states_by_key()) == (7 if enabled else 3)
        assert states_by_key()["rate"].state == "1300"
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        # HA may retain an unavailable registry placeholder after unloading.
        assert all(
            state is None or state.state == "unavailable"
            for state in states_by_key().values()
        )
