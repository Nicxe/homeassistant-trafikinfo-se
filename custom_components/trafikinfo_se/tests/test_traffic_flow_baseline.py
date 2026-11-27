"""Normalized comparisons and verified TrafficFlow 1.6 response regressions."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.trafikinfo_se.const import TRAFFIC_FLOW_SCHEMA_VERSION
from custom_components.trafikinfo_se.traffic_flow import (
    TRAFFIC_FLOW_BASELINE_ENABLED,
    TrafficFlowBaseline,
    TrafficFlowMeasurement,
    build_traffic_flow_discovery_request_xml,
    build_traffic_flow_site_request_xml,
    parse_traffic_flow_response,
    traffic_flow_comparison,
    traffic_flow_snapshot,
)

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def measurement(site_id="1", **changes):
    """A normalized detector with deliberately simple synthetic values."""
    return replace(
        TrafficFlowMeasurement(
            site_id=site_id,
            average_vehicle_speed=52.0,
            county_no=14,
            data_quality="good",
            deleted=False,
            measurement_period_s=60,
            measurement_side="northBound",
            measurement_time=NOW - timedelta(minutes=1),
            modified_time=NOW,
            region_id=5,
            specific_lane="lane1",
            vehicle_flow_rate=1300,
            vehicle_type="anyVehicle",
            geometry_wgs84=None,
        ),
        **changes,
    )


def baseline(site_id="1", **changes):
    """Internal adapter output for the enclosing observation timestamp."""
    return replace(
        TrafficFlowBaseline(
            site_id=site_id,
            measurement_side="northBound",
            vehicle_type="anyVehicle",
            measurement_time=NOW - timedelta(minutes=1),
            vehicle_flow_rate=1000.0,
            average_vehicle_speed=80.0,
        ),
        **changes,
    )


def compare(measurements=None, baselines=None, expected_site_ids=("1",)):
    return traffic_flow_comparison(
        [measurement()] if measurements is None else measurements,
        [baseline()] if baselines is None else baselines,
        expected_site_ids=expected_site_ids,
        now=NOW,
    )


def test_comparison_returns_absolute_and_relative_differences():
    result = compare()
    assert result.as_dict() == {
        "status": "valid",
        "flow_reference": 1000.0,
        "speed_reference": 80.0,
        "flow_deviation_percent": 30.0,
        "speed_deviation_percent": -35.0,
        "flow_deviation_absolute": 300.0,
        "speed_deviation_absolute": -28.0,
        "matched_detector_count": 1,
        "expected_detector_count": 1,
    }


def test_speed_uses_same_lane_weights_so_lane_mix_does_not_create_deviation():
    result = compare(
        [
            measurement("1", vehicle_flow_rate=100, average_vehicle_speed=40),
            measurement("2", vehicle_flow_rate=900, average_vehicle_speed=80),
        ],
        [
            baseline("1", vehicle_flow_rate=900, average_vehicle_speed=40),
            baseline("2", vehicle_flow_rate=100, average_vehicle_speed=80),
        ],
        expected_site_ids=("1", "2"),
    )
    assert result.status == "valid"
    assert result.flow_deviation_percent == 0
    assert result.speed_reference == 76
    assert result.speed_deviation_percent == 0


@pytest.mark.parametrize(
    ("measurements", "baselines", "expected", "status"),
    [
        ([measurement()], [], ("1",), "missing_reference"),
        ([measurement()], [baseline()], ("1", "2"), "incomplete"),
        ([measurement(), measurement("2")], [baseline()], ("1", "2"), "incomplete"),
        ([], [baseline()], ("1",), "incomplete"),
        ([measurement(), measurement()], [baseline()], ("1",), "invalid_data"),
        ([measurement()], [baseline(), baseline()], ("1",), "invalid_data"),
        ([measurement(), measurement("2")], [baseline()], ("1",), "invalid_data"),
        ([measurement()], [baseline(), baseline("2")], ("1",), "invalid_data"),
        ([measurement()], [baseline()], (), "invalid_data"),
        ([measurement()], [baseline()], ("1", "1"), "invalid_data"),
    ],
)
def test_incomplete_or_ambiguous_coverage_never_becomes_reduced_traffic(
    measurements, baselines, expected, status
):
    result = compare(measurements, baselines, expected)
    assert result.status == status
    assert all(
        value is None
        for key, value in result.as_dict().items()
        if "reference" in key or "deviation" in key
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"data_quality": "bad"},
        {"data_quality": None},
        {"deleted": True},
        {"measurement_time": NOW - timedelta(minutes=6)},
        {"measurement_time": NOW + timedelta(seconds=1)},
        {"measurement_time": NOW.replace(tzinfo=None)},
        {"measurement_time": None},
        {"measurement_side": "southBound"},
        {"measurement_side": None},
        {"vehicle_type": "car"},
        {"vehicle_flow_rate": None},
        {"vehicle_flow_rate": -1},
        {"vehicle_flow_rate": float("nan")},
        {"vehicle_flow_rate": True},
        {"measurement_period_s": 0},
        {"measurement_period_s": None},
    ],
)
def test_unusable_current_data_suppresses_comparison(changes):
    assert compare([measurement(**changes)]).status == "invalid_data"


@pytest.mark.parametrize(
    "changes",
    [
        {"measurement_side": "southBound"},
        {"vehicle_type": "car"},
        {"measurement_time": NOW},
        {"measurement_time": NOW.replace(tzinfo=None)},
        {"measurement_time": None},
    ],
)
def test_unusable_or_wrong_context_reference_suppresses_comparison(changes):
    assert compare(baselines=[baseline(**changes)]).status == "invalid_data"


def test_directions_must_also_match_across_detectors():
    result = compare(
        [measurement(), measurement("2", measurement_side="southBound")],
        [baseline(), baseline("2", measurement_side="southBound")],
        expected_site_ids=("1", "2"),
    )
    assert result.status == "invalid_data"


@pytest.mark.parametrize(
    "changes",
    [
        {"measurement_time": NOW - timedelta(seconds=30)},
        {"measurement_period_s": 30},
    ],
)
def test_observations_from_different_intervals_are_not_combined(changes):
    result = compare(
        [measurement(), measurement("2", **changes)],
        [baseline(), baseline("2")],
        expected_site_ids=("1", "2"),
    )
    assert result.status == "invalid_data"


def test_degraded_quality_retains_current_policy():
    assert compare([measurement(data_quality="degraded")]).status == "valid"


def test_zero_reference_keeps_absolute_difference_without_division_by_zero():
    result = compare(baselines=[baseline(vehicle_flow_rate=0, average_vehicle_speed=0)])
    assert result.status == "valid"
    assert result.flow_reference == 0
    assert result.speed_reference == 0
    assert result.flow_deviation_absolute == 1300
    assert result.speed_deviation_absolute == 52
    assert result.flow_deviation_percent is None
    assert result.speed_deviation_percent is None


def test_zero_current_flow_has_no_speed_comparison():
    result = compare([measurement(vehicle_flow_rate=0, average_vehicle_speed=None)])
    assert result.status == "valid"
    assert result.flow_deviation_percent == -100
    assert result.speed_reference is None
    assert result.speed_deviation_absolute is None
    assert result.speed_deviation_percent is None


def test_schema_16_requests_baseline_only_for_selected_site_polling():
    assert TRAFFIC_FLOW_SCHEMA_VERSION == "1.6"
    assert TRAFFIC_FLOW_BASELINE_ENABLED is True
    discovery = build_traffic_flow_discovery_request_xml(
        "test-key", latitude=57.7, longitude=11.9, radius_km=5
    )
    polling = build_traffic_flow_site_request_xml("test-key", site_ids=["1"])
    for request in (discovery, polling):
        assert 'schemaversion="1.6"' in request
    assert "BaselineTraffic" not in discovery
    assert "<INCLUDE>BaselineTraffic</INCLUDE>" in polling
    snapshot = parse_traffic_flow_response(
        "<RESPONSE><RESULT><TrafficFlow><SiteId>1</SiteId>"
        "<BaselineTraffic><Flow><Mean>5</Mean></Flow></BaselineTraffic>"
        "</TrafficFlow></RESULT></RESPONSE>",
        now=NOW,
    )
    assert snapshot.comparison is None
    assert traffic_flow_snapshot([measurement()], now=NOW).comparison is None


@pytest.mark.parametrize("value", [None, -1, float("nan"), float("inf")])
def test_unusable_speed_does_not_hide_valid_flow_comparison(value):
    for result in (
        compare([measurement(average_vehicle_speed=value)]),
        compare(baselines=[baseline(average_vehicle_speed=value)]),
    ):
        assert result.status == "valid"
        assert result.flow_deviation_percent == 30
        assert result.speed_reference is None
        assert result.speed_deviation_percent is None
        assert result.speed_deviation_absolute is None


@pytest.mark.parametrize("value", [None, -1, float("nan"), float("inf")])
def test_unusable_flow_mean_does_not_hide_valid_speed_comparison(value):
    result = compare(baselines=[baseline(vehicle_flow_rate=value)])
    assert result.status == "valid"
    assert result.speed_deviation_percent == -35
    assert result.flow_reference is None
    assert result.flow_deviation_percent is None
    assert result.flow_deviation_absolute is None


@pytest.mark.parametrize(
    ("value", "status"),
    [(None, "missing_reference"), (-1, "invalid_data"), (float("nan"), "invalid_data")],
)
def test_no_usable_reference_metric_reports_why(value, status):
    result = compare(
        baselines=[baseline(vehicle_flow_rate=value, average_vehicle_speed=value)]
    )
    assert result.status == status
    assert result.flow_reference is None
    assert result.speed_reference is None


def test_partial_metric_never_compares_partial_lane_totals():
    result = compare(
        [measurement(), measurement("2")],
        [baseline(), baseline("2", vehicle_flow_rate=None)],
        expected_site_ids=("1", "2"),
    )
    assert result.status == "valid"
    assert result.flow_reference is None
    assert result.flow_deviation_percent is None
    assert result.speed_reference == 80


def test_partial_metrics_on_different_lanes_do_not_produce_any_comparison():
    result = compare(
        [measurement(), measurement("2")],
        [baseline(average_vehicle_speed=None), baseline("2", vehicle_flow_rate=None)],
        expected_site_ids=("1", "2"),
    )
    assert result.status == "incomplete"
    assert result.flow_reference is None
    assert result.speed_reference is None


def test_small_positive_reference_preserves_precision_for_percentage():
    result = compare(
        [measurement(vehicle_flow_rate=1, average_vehicle_speed=0.002)],
        [baseline(vehicle_flow_rate=0.001, average_vehicle_speed=0.001)],
    )
    assert result.flow_reference == 0.001
    assert result.speed_reference == 0.001
    assert result.flow_deviation_absolute == pytest.approx(0.999)
    assert result.speed_deviation_absolute == pytest.approx(0.001)
    assert result.flow_deviation_percent == 99900
    assert result.speed_deviation_percent == 100


# Two records from a real 2026-11-18 response; IDs replaced with 1/2 and
# unrelated location metadata omitted. Means, StdDev and timestamps preserved.
VERIFIED_XML = """<RESPONSE><RESULT>
<TrafficFlow><SiteId>1</SiteId>
<MeasurementTime>2026-11-18T17:39:00.000+01:00</MeasurementTime>
<MeasurementOrCalculationPeriod>60</MeasurementOrCalculationPeriod>
<VehicleType>anyVehicle</VehicleType><VehicleFlowRate>1440</VehicleFlowRate>
<AverageVehicleSpeed>54.75</AverageVehicleSpeed><Deleted>false</Deleted>
<DataQuality>good</DataQuality><SpecificLane>lane2</SpecificLane>
<MeasurementSide>northBound</MeasurementSide>
<BaselineTraffic><Flow><Mean>922.2</Mean><StdDev>202.8</StdDev></Flow>
<Speed><Mean>60.51</Mean><StdDev>2.78</StdDev></Speed></BaselineTraffic>
<ModifiedTime>2026-11-18T16:39:05.308Z</ModifiedTime></TrafficFlow>
<TrafficFlow><SiteId>2</SiteId>
<MeasurementTime>2026-11-18T17:39:00.000+01:00</MeasurementTime>
<MeasurementOrCalculationPeriod>60</MeasurementOrCalculationPeriod>
<VehicleType>anyVehicle</VehicleType><VehicleFlowRate>360</VehicleFlowRate>
<AverageVehicleSpeed>43.74</AverageVehicleSpeed><Deleted>false</Deleted>
<DataQuality>good</DataQuality><SpecificLane>lane1</SpecificLane>
<MeasurementSide>northBound</MeasurementSide>
<BaselineTraffic><Flow><Mean>206.4</Mean><StdDev>41.4</StdDev></Flow>
<Speed><Mean>59.41</Mean><StdDev>2.59</StdDev></Speed></BaselineTraffic>
<ModifiedTime>2026-11-18T16:39:04.822Z</ModifiedTime></TrafficFlow>
</RESULT></RESPONSE>"""
VERIFIED_NOW = datetime(2026, 11, 18, 16, 40, tzinfo=UTC)


@pytest.mark.parametrize("namespace", ["", ' xmlns="urn:test"'])
def test_real_xml_comparison_preserves_decimal_means_and_uses_current_weights(
    namespace,
):
    snapshot = parse_traffic_flow_response(
        VERIFIED_XML.replace("<RESPONSE>", f"<RESPONSE{namespace}>"),
        now=VERIFIED_NOW,
        expected_site_ids=("1", "2"),
    )
    assert snapshot.total_flow_rate == 1800
    assert snapshot.weighted_average_speed == pytest.approx(52.55)
    result = snapshot.comparison
    assert result.status == "valid"
    assert result.flow_reference == pytest.approx(1128.6)
    assert result.speed_reference == pytest.approx(60.29)
    assert result.flow_deviation_absolute == pytest.approx(671.4)
    assert result.speed_deviation_absolute == pytest.approx(-7.742)
    assert result.flow_deviation_percent == pytest.approx(59.49)
    assert result.speed_deviation_percent == pytest.approx(-12.84)


@pytest.mark.parametrize(
    ("xml_text", "expected_ids", "status"),
    [
        (VERIFIED_XML, ("1", "2", "3"), "incomplete"),
        (
            VERIFIED_XML.replace("<DataQuality>good", "<DataQuality>bad"),
            ("1", "2"),
            "invalid_data",
        ),
        (
            VERIFIED_XML.replace("<Mean>", "<Unused>").replace("</Mean>", "</Unused>"),
            ("1", "2"),
            "missing_reference",
        ),
    ],
)
def test_real_xml_invalid_comparison_keeps_available_current_data(
    xml_text, expected_ids, status
):
    snapshot = parse_traffic_flow_response(
        xml_text, now=VERIFIED_NOW, expected_site_ids=expected_ids
    )
    assert snapshot.comparison.status == status
    assert snapshot.comparison.flow_reference is None
    if status != "invalid_data":
        assert snapshot.total_flow_rate == 1800
        assert snapshot.weighted_average_speed == pytest.approx(52.55)


def test_malformed_baseline_never_breaks_current_values():
    snapshot = parse_traffic_flow_response(
        VERIFIED_XML.replace("<Mean>922.2</Mean>", "<Mean>invalid</Mean>").replace(
            "<Mean>60.51</Mean>", "<Mean>NaN</Mean>"
        ),
        now=VERIFIED_NOW,
        expected_site_ids=("1", "2"),
    )
    assert snapshot.comparison.status == "invalid_data"
    assert snapshot.total_flow_rate == 1800
    assert snapshot.weighted_average_speed == pytest.approx(52.55)
