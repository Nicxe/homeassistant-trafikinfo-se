from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from custom_components.trafikinfo_se.config_flow import TrafikinfoSEConfigFlow
from custom_components.trafikinfo_se.const import (
    CONF_MAX_ITEMS,
    ENTRY_KIND_ROAD_CONDITION,
)
from custom_components.trafikinfo_se.coordinator import (
    TrafikinfoAPIError,
    TrafikinfoAuthenticationError,
    TrafikinfoParseError,
)
from custom_components.trafikinfo_se.road_condition import (
    ROAD_CONDITION_ICE_SNOW,
    ROAD_CONDITION_NORMAL,
    ROAD_CONDITION_VERY_DIFFICULT,
    RoadConditionCoordinator,
    build_road_condition_request_xml,
    parse_road_condition_response,
)

ROAD_CONDITION_XML = """\
<RESPONSE>
  <RESULT>
    <RoadCondition>
      <Id>normal-84</Id>
      <ConditionCode>1</ConditionCode>
      <ConditionText>Normalt väglag</ConditionText>
      <CountyNo>14</CountyNo>
      <Deleted>false</Deleted>
      <EndTime>2099-08-26T12:00:00Z</EndTime>
      <Geometry><WGS84>LINESTRING (11.9700 57.7000, 11.9800 57.7100)</WGS84></Geometry>
      <LocationText>Väg 84 mellan Testby och Testköping</LocationText>
      <ModifiedTime>2026-08-26T10:00:00Z</ModifiedTime>
      <RoadNumber>Väg 84</RoadNumber>
      <RoadNumberNumeric>84</RoadNumberNumeric>
      <SafetyRelatedMessage>false</SafetyRelatedMessage>
      <StartTime>2026-08-26T09:00:00Z</StartTime>
    </RoadCondition>
    <RoadCondition>
      <Id>snow-848</Id>
      <Cause>Frost</Cause>
      <Cause>Snöfall</Cause>
      <ConditionCode>4</ConditionCode>
      <ConditionInfo>Packad snö</ConditionInfo>
      <ConditionText>Is- och snövägbana</ConditionText>
      <CountyNo>14</CountyNo>
      <Deleted>false</Deleted>
      <Geometry><WGS84>POINT (12.1000 57.8000)</WGS84></Geometry>
      <LocationText>Väg 848 vid Testplats</LocationText>
      <Measure>Plogning</Measure>
      <Measure>Sandning</Measure>
      <ModifiedTime>2026-08-26T10:05:00Z</ModifiedTime>
      <RoadNumber>Väg 848</RoadNumber>
      <RoadNumberNumeric>848</RoadNumberNumeric>
      <SafetyRelatedMessage>true</SafetyRelatedMessage>
      <StartTime>2026-08-26T09:30:00Z</StartTime>
      <Warning>Halka</Warning>
      <Warning>Snöfall</Warning>
    </RoadCondition>
    <RoadCondition>
      <Id>expired</Id>
      <ConditionCode>3</ConditionCode>
      <Deleted>false</Deleted>
      <EndTime>2020-01-01T00:00:00Z</EndTime>
      <RoadNumber>Väg 45</RoadNumber>
    </RoadCondition>
    <RoadCondition>
      <Id>deleted</Id>
      <ConditionCode>3</ConditionCode>
      <Deleted>true</Deleted>
      <RoadNumber>Väg 40</RoadNumber>
    </RoadCondition>
  </RESULT>
  <INFO>
    <LASTMODIFIED datetime="2026-08-26T10:05:00Z" />
    <LASTCHANGEID>12345</LASTCHANGEID>
  </INFO>
</RESPONSE>
"""


def test_build_request_uses_supported_model_and_fields() -> None:
    request = build_road_condition_request_xml("test-key", limit=2000)

    assert 'objecttype="RoadCondition"' in request
    assert 'namespace="Road.TrafficInfo"' in request
    assert 'schemaversion="1.3"' in request
    assert '<EQ name="Deleted" value="false" />' in request
    assert "<INCLUDE>ConditionCode</INCLUDE>" in request
    assert "<INCLUDE>Geometry</INCLUDE>" in request
    assert "<INCLUDE>Warning</INCLUDE>" in request


def test_config_flow_offers_road_condition_without_incident_only_fields() -> None:
    flow = TrafikinfoSEConfigFlow()
    values = {option["value"] for option in flow._entry_kind_options()}

    assert ENTRY_KIND_ROAD_CONDITION in values

    flow._entry_kind = ENTRY_KIND_ROAD_CONDITION
    schema = flow._schema_common_tail(
        default_max_items=25,
        default_sort_mode="relevance",
        default_message_types=["Olycka"],
    )
    assert [marker.schema for marker in schema] == [CONF_MAX_ITEMS]


@pytest.mark.asyncio
async def test_reauthentication_flow_requests_replacement_api_key() -> None:
    flow = TrafikinfoSEConfigFlow()

    result = await flow.async_step_reauth_confirm()

    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"
    assert [marker.schema for marker in result["data_schema"].schema] == ["api_key"]


def test_parse_response_returns_active_conditions_and_summary() -> None:
    snapshot = parse_road_condition_response(
        ROAD_CONDITION_XML,
        now=datetime.fromisoformat("2026-08-26T10:30:00+00:00"),
    )

    assert [condition.condition_id for condition in snapshot.conditions] == [
        "snow-848",
        "normal-84",
    ]
    assert snapshot.worst_state == ROAD_CONDITION_ICE_SNOW
    assert snapshot.hazardous_count == 1
    assert snapshot.total_count == 2
    assert snapshot.last_change_id == "12345"

    snow = snapshot.conditions[0]
    assert snow.causes == ["Frost", "Snöfall"]
    assert snow.measures == ["Plogning", "Sandning"]
    assert snow.warnings == ["Halka", "Snöfall"]
    assert snow.county_no == [14]
    assert snow.as_dict()["state"] == ROAD_CONDITION_ICE_SNOW


def test_parse_empty_success_is_no_data_not_error() -> None:
    snapshot = parse_road_condition_response("<RESPONSE><RESULT /></RESPONSE>")

    assert snapshot.conditions == []
    assert snapshot.worst_state == "no_data"
    assert snapshot.hazardous_count == 0


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
        parse_road_condition_response(xml_text)


@pytest.fixture
def coordinator() -> RoadConditionCoordinator:
    instance = object.__new__(RoadConditionCoordinator)
    instance._filter_roads = []
    instance._filter_mode = "county"
    instance._counties = {"all"}
    instance._latitude = 57.70
    instance._longitude = 11.97
    instance._radius_km = 25.0
    return instance


def test_road_filter_is_exact_unless_prefix_wildcard_is_used(
    coordinator: RoadConditionCoordinator,
) -> None:
    snapshot = parse_road_condition_response(
        ROAD_CONDITION_XML,
        now=datetime.fromisoformat("2026-08-26T10:30:00+00:00"),
    )

    coordinator._filter_roads = ["84"]
    assert [
        item.condition_id for item in coordinator.filter_conditions(snapshot.conditions)
    ] == ["normal-84"]

    coordinator._filter_roads = ["84*"]
    assert [
        item.condition_id for item in coordinator.filter_conditions(snapshot.conditions)
    ] == [
        "snow-848",
        "normal-84",
    ]


def test_road_filter_normalizes_e_roads_and_named_road_numbers(
    coordinator: RoadConditionCoordinator,
) -> None:
    snapshot = parse_road_condition_response(
        ROAD_CONDITION_XML,
        now=datetime.fromisoformat("2026-08-26T10:30:00+00:00"),
    )
    template = snapshot.conditions[0]
    e45 = replace(
        template,
        condition_id="e45",
        road_number="E 45",
        road_number_numeric=45,
        location_text="E 45 Göteborg",
    )
    road_570 = replace(
        template,
        condition_id="road-570",
        road_number="Götaälvbron väg 570",
        road_number_numeric=None,
        location_text="Götaälvbron väg 570 Lundbyleden",
    )

    coordinator._filter_roads = ["E45"]
    assert coordinator.filter_conditions([e45, road_570]) == [e45]

    coordinator._filter_roads = ["570"]
    assert coordinator.filter_conditions([e45, road_570]) == [road_570]


def test_coordinate_and_county_filters(coordinator: RoadConditionCoordinator) -> None:
    snapshot = parse_road_condition_response(
        ROAD_CONDITION_XML,
        now=datetime.fromisoformat("2026-08-26T10:30:00+00:00"),
    )

    coordinator._filter_mode = "coordinate"
    coordinator._radius_km = 3
    assert [
        item.condition_id for item in coordinator.filter_conditions(snapshot.conditions)
    ] == ["normal-84"]

    coordinator._filter_mode = "county"
    coordinator._counties = {"1"}
    assert coordinator.filter_conditions(snapshot.conditions) == []


def test_known_condition_codes_have_stable_states() -> None:
    snapshot = parse_road_condition_response(
        ROAD_CONDITION_XML,
        now=datetime.fromisoformat("2026-08-26T10:30:00+00:00"),
    )

    states = {item.condition_code: item.state for item in snapshot.conditions}
    assert states[1] == ROAD_CONDITION_NORMAL
    assert states[4] == ROAD_CONDITION_ICE_SNOW
    assert ROAD_CONDITION_VERY_DIFFICULT != ROAD_CONDITION_NORMAL
