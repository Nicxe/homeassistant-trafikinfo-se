# Traffic-flow reference comparisons

Trafikverket's [TrafficFlow 1.6 schema](https://data.trafikverket.se/apb/prod/schematree/Road.TrafficInfo.TrafficFlow/1.6/?annotations=true)
defines optional historical references for the current measurement time.
The integration requests `BaselineTraffic` in the regular query for a selected
detector group. It reads `Flow.Mean` in vehicles per hour and `Speed.Mean` on the
same speed scale as the current measurement. `MeasurementTime` marks the end of
the observation interval. The published schema leaves the historical calculation
period unspecified.

## How comparisons are calculated

The integration matches all configured detector IDs and requires current,
usable measurements from the same direction, vehicle category and observation
interval. One missing or invalid detector prevents a comparison of that group.
Flow and speed references can be absent independently. A metric is shown when
its own reference data is complete for the detectors contributing to it.
The regular flow, speed and quality sensors continue to describe available
current measurements.

Reference flow is summed across the configured detectors. Reference speed uses
the current flow of each lane as its weight, just as the current speed does.
This compares speeds for the same distribution of vehicles across lanes.

Absolute deviation is current minus reference. Percentage deviation divides the
difference by the reference and multiplies it by 100. A zero reference gives
only an absolute difference. Zero current flow gives no speed comparison.

## Sensors and card

Each traffic-flow entry has sensors for reference flow, reference speed, flow
deviation (%) and speed deviation (%). Missing values appear as unknown. The
four sensors share the existing one-minute update with the current measurements.

The card uses the computed comparison from the flow sensor. The selected flow,
speed and quality entities must refer to the same group and observation time.
Data quality appears separately from traffic differences. The comparison
describes traffic relative to a historical reference and does not classify queues.

## Verification

On 18 November 2026, the public schema index listed 1.6, and the Trafikverket
API returned live measurements with the documented XML structure. In one
nearby search, 474 of 500 returned records had both references. Both schema
versions returned zero rows for the detector IDs originally saved in HAdev.
A separate active group supplied six synchronized detector records with
both reference values.

A live run through the updated coordinator and sensors produced 4,260 versus
3,787.8 vehicles per hour (+12.47%) and 51.69 versus 60.14 km/h (−14.04%).
The annotated schema does not specify a separate unit for `Speed.Mean`, so
the integration uses the existing `AverageVehicleSpeed` convention.

After synchronization and restart, HAdev loaded all eight integration entries
and served the updated card. The traffic-flow entry registered all four new
sensors and reloaded successfully. Its saved group returned zero measurements,
which was visible as `no_data` with unknown references and deviations.

All 128 shared Python tests and 80 card tests passed locally. They cover
missing or partial references, zero values, stale data, aggregation, entity
setup and card rendering.
