from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.trafikinfo_se.coordinator import (
    TrafikinfoCoordinator,
    TrafikinfoEvent,
)

BASE_EVENT = TrafikinfoEvent(
    situation_id="situation",
    deviation_id="deviation",
    icon_id=None,
    message_type="Olycka",
    message_type_value="Accident",
    header="Test event",
    message="Test event",
    severity_code=2,
    severity_text="Moderate",
    road_number=None,
    road_name=None,
    county_no=[14],
    affected_direction=None,
    affected_direction_value=None,
    start_time=None,
    end_time=None,
    valid_until_further_notice=None,
    suspended=None,
    location_descriptor=None,
    positional_description=None,
    traffic_restriction_type=None,
    temporary_limit=None,
    number_of_lanes_restricted=None,
    safety_related_message=False,
    weblink=None,
    geometry_wgs84="POINT (11.97 57.70)",
    version_time=None,
    publication_time=None,
    modified_time=None,
)


@pytest.fixture
def coordinator() -> TrafikinfoCoordinator:
    return object.__new__(TrafikinfoCoordinator)


@pytest.mark.parametrize(
    ("token", "road_number", "road_name", "expected"),
    [
        ("84", "84", "Väg 84", True),
        ("84", "848", "Vallervägen (Väg 848)", False),
        ("e4", "E4", "Europaväg E4", True),
        ("e4", "E45", "Europaväg E45", False),
        ("71*", "71", "Väg 71", True),
        ("71*", "712", "Väg 712", True),
        ("71*", "713", "Väg 713", True),
        ("71*", "715", "Väg 715", True),
        ("71*", "72", "Väg 72", False),
        ("vallervägen", "848", "Vallervägen (Väg 848)", True),
        ("valler", "848", "Vallervägen (Väg 848)", True),
        ("*", "848", "Vallervägen (Väg 848)", False),
        ("7*1", "711", "Väg 711", False),
    ],
)
def test_road_filter_match(
    coordinator: TrafikinfoCoordinator,
    token: str,
    road_number: str,
    road_name: str,
    expected: bool,
) -> None:
    event = replace(BASE_EVENT, road_number=road_number, road_name=road_name)

    assert coordinator._road_filter_match(event, [token]) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Väg 84", "84"),
        ("Road 71*", "71*"),
        ("  E4  ", "e4"),
        ("Vallervägen", "vallervägen"),
    ],
)
def test_normalize_road_filter_token(
    coordinator: TrafikinfoCoordinator, value: str, expected: str
) -> None:
    assert coordinator._normalize_road_filter_token(value) == expected


def test_apply_road_filter_supports_exact_and_prefix_tokens(
    coordinator: TrafikinfoCoordinator,
) -> None:
    coordinator._filter_roads = ["84", "Väg 71*", "E4"]
    coordinator._road_filter_safety_bypass = False
    events = [
        replace(BASE_EVENT, deviation_id="84", road_number="84", road_name="Väg 84"),
        replace(
            BASE_EVENT,
            deviation_id="848",
            road_number="848",
            road_name="Vallervägen (Väg 848)",
        ),
        replace(BASE_EVENT, deviation_id="712", road_number="712", road_name="Väg 712"),
        replace(
            BASE_EVENT, deviation_id="E4", road_number="E4", road_name="Europaväg E4"
        ),
        replace(
            BASE_EVENT, deviation_id="E45", road_number="E45", road_name="Europaväg E45"
        ),
    ]

    filtered = coordinator._apply_road_filter(events)

    assert [event.deviation_id for event in filtered] == ["84", "712", "E4"]
