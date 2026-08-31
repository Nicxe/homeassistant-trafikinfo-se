from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from custom_components.trafikinfo_se import config_flow as config_flow_module
from custom_components.trafikinfo_se import traffic_flow
from custom_components.trafikinfo_se.config_flow import TrafikinfoSEConfigFlow
from custom_components.trafikinfo_se.const import (
    CONF_API_KEY,
    CONF_TRAFFIC_FLOW_SITE_IDS,
    CONF_TRAFFIC_FLOW_SITE_LABEL,
    CONF_TRAFFIC_FLOW_SITE_LATITUDE,
    CONF_TRAFFIC_FLOW_SITE_LONGITUDE,
    ENTRY_KIND_TRAFFIC_FLOW,
)
from custom_components.trafikinfo_se.coordinator import (
    TrafikinfoAPIError,
    TrafikinfoAuthenticationError,
    TrafikinfoParseError,
)
from custom_components.trafikinfo_se.traffic_flow import (
    TRAFFIC_FLOW_QUALITY_BAD,
    TRAFFIC_FLOW_QUALITY_STALE,
    TrafficFlowMeasurement,
    build_traffic_flow_discovery_request_xml,
    build_traffic_flow_site_request_xml,
    group_traffic_flow_sites,
    parse_traffic_flow_response,
    traffic_flow_snapshot,
)

TRAFFIC_FLOW_XML = """\
<RESPONSE>
  <RESULT>
    <TrafficFlow>
      <AverageVehicleSpeed>60</AverageVehicleSpeed>
      <CountyNo>14</CountyNo>
      <DataQuality>good</DataQuality>
      <Deleted>false</Deleted>
      <Geometry><WGS84>POINT (11.97000 57.70000)</WGS84></Geometry>
      <MeasurementOrCalculationPeriod>60</MeasurementOrCalculationPeriod>
      <MeasurementSide>northBound</MeasurementSide>
      <MeasurementTime>2026-08-26T10:01:00Z</MeasurementTime>
      <ModifiedTime>2026-08-26T10:01:05Z</ModifiedTime>
      <RegionId>5</RegionId>
      <SiteId>1001</SiteId>
      <SpecificLane>lane1</SpecificLane>
      <VehicleFlowRate>600</VehicleFlowRate>
      <VehicleType>anyVehicle</VehicleType>
    </TrafficFlow>
    <TrafficFlow>
      <AverageVehicleSpeed>90</AverageVehicleSpeed>
      <CountyNo>14</CountyNo>
      <DataQuality>degraded</DataQuality>
      <Deleted>false</Deleted>
      <Geometry><WGS84>POINT (11.97004 57.70000)</WGS84></Geometry>
      <MeasurementOrCalculationPeriod>60</MeasurementOrCalculationPeriod>
      <MeasurementSide>northBound</MeasurementSide>
      <MeasurementTime>2026-08-26T10:01:00Z</MeasurementTime>
      <ModifiedTime>2026-08-26T10:01:05Z</ModifiedTime>
      <RegionId>5</RegionId>
      <SiteId>1002</SiteId>
      <SpecificLane>lane2</SpecificLane>
      <VehicleFlowRate>300</VehicleFlowRate>
      <VehicleType>anyVehicle</VehicleType>
    </TrafficFlow>
    <TrafficFlow>
      <AverageVehicleSpeed>30</AverageVehicleSpeed>
      <CountyNo>14</CountyNo>
      <DataQuality>bad</DataQuality>
      <Deleted>false</Deleted>
      <Geometry><WGS84>POINT (11.97008 57.70000)</WGS84></Geometry>
      <MeasurementOrCalculationPeriod>60</MeasurementOrCalculationPeriod>
      <MeasurementSide>northBound</MeasurementSide>
      <MeasurementTime>2026-08-26T10:01:00Z</MeasurementTime>
      <ModifiedTime>2026-08-26T10:01:05Z</ModifiedTime>
      <RegionId>5</RegionId>
      <SiteId>1003</SiteId>
      <SpecificLane>lane3</SpecificLane>
      <VehicleFlowRate>200</VehicleFlowRate>
      <VehicleType>anyVehicle</VehicleType>
    </TrafficFlow>
    <TrafficFlow>
      <SiteId>deleted</SiteId>
      <Deleted>true</Deleted>
    </TrafficFlow>
  </RESULT>
  <INFO>
    <LASTMODIFIED datetime="2026-08-26T10:01:05Z" />
    <LASTCHANGEID>12345</LASTCHANGEID>
  </INFO>
</RESPONSE>
"""


class _TrafficFlowEntry:
    def __init__(self) -> None:
        self.entry_id = "test-entry"
        self.title = "Traffic flow test"
        self.options: dict[str, object] = {}
        self.data = {
            CONF_API_KEY: "test-key",
            CONF_TRAFFIC_FLOW_SITE_IDS: ["1001", "1002", "1003"],
            CONF_TRAFFIC_FLOW_SITE_LABEL: "0.4 km • norrgående • 3 körfält",
            CONF_TRAFFIC_FLOW_SITE_LATITUDE: 57.7,
            CONF_TRAFFIC_FLOW_SITE_LONGITUDE: 11.97,
        }

    def async_on_unload(self, _callback: object) -> None:
        """Match the ConfigEntry lifecycle hook used by the coordinator."""


def test_discovery_request_uses_current_model_and_server_side_near_filter() -> None:
    request = build_traffic_flow_discovery_request_xml(
        "test-key",
        latitude=57.7,
        longitude=11.97,
        radius_km=25,
    )

    assert 'objecttype="TrafficFlow"' in request
    assert 'namespace="Road.TrafficInfo"' in request
    assert 'schemaversion="1.5"' in request
    assert '<EQ name="VehicleType" value="anyVehicle" />' in request
    assert '<NEAR name="Geometry.WGS84"' in request
    assert 'maxdistance="25000"' in request
    assert "<INCLUDE>DataQuality</INCLUDE>" in request


def test_county_discovery_and_site_requests_are_server_filtered() -> None:
    discovery = build_traffic_flow_discovery_request_xml(
        "test-key",
        latitude=57.7,
        longitude=11.97,
        radius_km=25,
        county_no="14",
    )
    selected = build_traffic_flow_site_request_xml(
        "test-key", site_ids=["1003", "1001", "1002"]
    )

    assert '<EQ name="CountyNo" value="14" />' in discovery
    assert "<NEAR" not in discovery
    assert '<IN name="SiteId" value="1001, 1002, 1003" />' in selected


def test_parse_response_aggregates_only_usable_lanes() -> None:
    snapshot = parse_traffic_flow_response(
        TRAFFIC_FLOW_XML,
        now=datetime.fromisoformat("2026-08-26T10:02:00+00:00"),
    )

    assert snapshot.total_measurement_count == 3
    assert snapshot.valid_measurement_count == 2
    assert snapshot.total_flow_rate == 900
    assert snapshot.weighted_average_speed == pytest.approx(70.0)
    assert snapshot.data_quality == TRAFFIC_FLOW_QUALITY_BAD
    assert snapshot.data_age_minutes == pytest.approx(1.0)
    assert snapshot.last_change_id == "12345"


def test_stale_measurements_are_not_presented_as_current_values() -> None:
    snapshot = parse_traffic_flow_response(
        TRAFFIC_FLOW_XML.replace(
            "<DataQuality>bad</DataQuality>", "<DataQuality>good</DataQuality>"
        ),
        now=datetime.fromisoformat("2026-08-26T10:10:00+00:00"),
    )

    assert snapshot.data_quality == TRAFFIC_FLOW_QUALITY_STALE
    assert snapshot.valid_measurement_count == 0
    assert snapshot.total_flow_rate is None
    assert snapshot.weighted_average_speed is None


@pytest.mark.parametrize(
    ("xml_text", "error_type"),
    [
        ("not xml", TrafikinfoParseError),
        (
            "<RESPONSE><RESULT><ERROR><MESSAGE>Invalid authentication key</MESSAGE></ERROR></RESULT></RESPONSE>",
            TrafikinfoAuthenticationError,
        ),
        (
            "<RESPONSE><RESULT><ERROR><MESSAGE>Query failed</MESSAGE></ERROR></RESULT></RESPONSE>",
            TrafikinfoAPIError,
        ),
    ],
)
def test_parse_response_surfaces_actionable_errors(
    xml_text: str, error_type: type[Exception]
) -> None:
    with pytest.raises(error_type):
        parse_traffic_flow_response(xml_text)


def test_grouping_combines_nearby_lanes_but_keeps_directions_separate() -> None:
    snapshot = parse_traffic_flow_response(
        TRAFFIC_FLOW_XML,
        now=datetime.fromisoformat("2026-08-26T10:02:00+00:00"),
    )
    first = snapshot.measurements[0]
    opposite = replace(
        first,
        site_id="2001",
        measurement_side="southBound",
        specific_lane="lane1",
    )

    sites = group_traffic_flow_sites(
        [*snapshot.measurements, opposite],
        origin_latitude=57.7,
        origin_longitude=11.97,
        now=datetime.fromisoformat("2026-08-26T10:02:00+00:00"),
    )

    assert len(sites) == 2
    northbound = next(site for site in sites if site.measurement_side == "northBound")
    assert northbound.site_ids == ("1001", "1002", "1003")
    assert northbound.snapshot.total_flow_rate == 900


def test_empty_success_is_no_data_not_an_api_error() -> None:
    snapshot = parse_traffic_flow_response("<RESPONSE><RESULT /></RESPONSE>")

    assert snapshot.measurements == []
    assert snapshot.data_quality == "no_data"
    assert snapshot.total_flow_rate is None


def test_config_flow_offers_traffic_flow_as_a_separate_entry_kind() -> None:
    flow = TrafikinfoSEConfigFlow()
    values = {option["value"] for option in flow._entry_kind_options()}

    assert ENTRY_KIND_TRAFFIC_FLOW in values


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_key"),
    [
        (TrafikinfoAuthenticationError("invalid key"), "invalid_auth"),
        (TrafikinfoAPIError("temporarily unavailable"), "cannot_connect"),
        (RuntimeError("unexpected"), "unknown"),
    ],
)
async def test_config_flow_maps_discovery_errors_to_actionable_messages(
    hass, monkeypatch, error: Exception, expected_key: str
) -> None:
    async def _raise_error(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(
        config_flow_module, "async_fetch_traffic_flow_sites", _raise_error
    )
    flow = TrafikinfoSEConfigFlow()
    flow.hass = hass
    flow._api_key = "test-key"

    result = await flow._async_discover_traffic_flow_sites(
        latitude=57.7,
        longitude=11.97,
        radius_km=25,
    )

    assert result == expected_key


@pytest.mark.asyncio
async def test_config_flow_reports_empty_discovery_separately(hass, monkeypatch) -> None:
    async def _empty_result(*_args, **_kwargs):
        return []

    monkeypatch.setattr(
        config_flow_module, "async_fetch_traffic_flow_sites", _empty_result
    )
    flow = TrafikinfoSEConfigFlow()
    flow.hass = hass
    flow._api_key = "test-key"

    result = await flow._async_discover_traffic_flow_sites(
        latitude=57.7,
        longitude=11.97,
        radius_km=25,
    )

    assert result == "no_traffic_flow_sites"


def test_snapshot_attributes_keep_raw_and_effective_quality_separate() -> None:
    measurement = TrafficFlowMeasurement(
        site_id="1001",
        average_vehicle_speed=72.0,
        county_no=14,
        data_quality="good",
        deleted=False,
        measurement_period_s=60,
        measurement_side="northBound",
        measurement_time=datetime.fromisoformat("2026-08-26T10:00:00+00:00"),
        modified_time=datetime.fromisoformat("2026-08-26T10:00:05+00:00"),
        region_id=5,
        specific_lane="lane1",
        vehicle_flow_rate=600,
        vehicle_type="anyVehicle",
        geometry_wgs84="POINT (11.97 57.7)",
    )
    now = datetime.fromisoformat("2026-08-26T10:10:00+00:00")
    attributes = measurement.as_dict(now=now)
    snapshot = traffic_flow_snapshot([measurement], now=now)

    assert attributes["data_quality"] == "good"
    assert attributes["effective_quality"] == "stale"
    assert snapshot.data_quality == "stale"


@pytest.mark.asyncio
async def test_coordinator_fetches_only_selected_site_ids(hass, monkeypatch) -> None:
    async def _fake_post_xml(_hass, payload: str) -> str:
        assert '<IN name="SiteId" value="1001, 1002, 1003" />' in payload
        assert "<NEAR" not in payload
        assert '<EQ name="CountyNo"' not in payload
        current_time = datetime.now(UTC).isoformat()
        return TRAFFIC_FLOW_XML.replace(
            "2026-08-26T10:01:00Z", current_time
        ).replace("2026-08-26T10:01:05Z", current_time)

    monkeypatch.setattr(traffic_flow, "_async_post_xml", _fake_post_xml)

    coordinator = traffic_flow.TrafficFlowCoordinator(hass, _TrafficFlowEntry())
    await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    assert coordinator.data is not None
    assert coordinator.data.total_flow_rate == 900
    assert coordinator.data.weighted_average_speed == pytest.approx(70.0)


@pytest.mark.asyncio
async def test_coordinator_reports_missing_selected_site_ids(hass) -> None:
    entry = _TrafficFlowEntry()
    entry.data[CONF_TRAFFIC_FLOW_SITE_IDS] = []

    coordinator = traffic_flow.TrafficFlowCoordinator(hass, entry)
    await coordinator.async_refresh()

    assert coordinator.last_update_success is False
    assert coordinator.data is None
