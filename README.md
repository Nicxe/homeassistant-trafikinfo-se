# Trafikinfo SE

[![Buy me a Coffee](https://img.shields.io/badge/Support-Buy%20me%20a%20coffee-fdd734?logo=buy-me-a-coffee)](https://www.buymeacoffee.com/NiklasV)
![GitHub Release](https://img.shields.io/github/v/release/Nicxe/homeassistant-trafikinfo-se)
![GitHub Downloads](https://img.shields.io/github/downloads/Nicxe/homeassistant-trafikinfo-se/total)
![Latest Release Downloads](https://img.shields.io/github/downloads/Nicxe/homeassistant-trafikinfo-se/latest/total)

Trafikinfo SE brings current Swedish road traffic information from [Trafikverket](https://www.trafikverket.se/) into Home Assistant. You can monitor incidents, road conditions, traffic flow, and travel time on predefined routes.

The repository contains both the Home Assistant integration and five bundled Lovelace cards. The integration installs and updates the card resource automatically.

## Contents

- [Highlights](#highlights)
- [Requirements](#requirements)
- [Installation](#installation)
- [Set up the integration](#set-up-the-integration)
- [Traffic incidents](#traffic-incidents)
- [Road conditions](#road-conditions)
- [Traffic flow](#traffic-flow)
- [Travel-time routes](#travel-time-routes)
- [Dashboard cards](#dashboard-cards)
- [Automations and notifications](#automations-and-notifications)
- [Troubleshooting](#troubleshooting)
- [Data source and update intervals](#data-source-and-update-intervals)
- [Migration and releases](#migration-and-releases)
- [Screenshots](#screenshots)
- [License](#license)

## Highlights

- Six traffic-incident categories, including accidents, obstacles, restrictions, and roadworks
- Coordinate-and-radius, county, Sweden-wide, and road-number filtering
- Exact road-number matching with optional trailing wildcards
- Section-level road-condition assessments
- Current traffic flow, speed, and data quality from lane detectors
- Travel time, delay, and traffic status for Trafikverket routes
- Five visual dashboard cards with UI editors
- Home Assistant events and a notification blueprint for new or updated accidents and obstacles
- UI configuration, reconfiguration, and API-key recovery

## Requirements

- Home Assistant with network access to Trafikverket's API
- A Trafikverket API key from the [Trafikverket data portal](https://data.trafikverket.se/home)
- [HACS](https://www.hacs.xyz/) for the recommended installation method

## Installation

### Install with HACS (recommended)

[![Open this repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Nicxe&repository=homeassistant-trafikinfo-se&category=integration)

1. Select the button above
2. Download **Trafikinfo SE** as an integration
3. Restart Home Assistant

To add the repository manually in HACS:

1. Open **HACS**
2. Open the menu and select **Custom repositories**
3. Enter `https://github.com/Nicxe/homeassistant-trafikinfo-se`
4. Select **Integration** as the category
5. Download the integration and restart Home Assistant

### Install without HACS

1. Download `trafikinfo_se.zip` from the [latest release](https://github.com/Nicxe/homeassistant-trafikinfo-se/releases/latest)
2. Extract the archive into `config/custom_components/`
3. Confirm that `config/custom_components/trafikinfo_se/manifest.json` exists
4. Restart Home Assistant

### Bundled dashboard cards

The dashboard cards require no separate HACS installation. When the integration starts, it:

- copies the bundled JavaScript file to `config/www/trafikinfo-se-alert-card.js`
- creates or updates the Lovelace module resource at `/local/trafikinfo-se-alert-card.js?v=...`
- changes the resource version after an update so the browser loads the new file

Reload the browser once after installing or updating the integration.

## Set up the integration

[![Add Trafikinfo SE to Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=trafikinfo_se)

1. Select the button above, or open **Settings > Devices & services**
2. Select **Add integration**
3. Search for **Trafikinfo SE**
4. Enter your Trafikverket API key
5. Choose an entry type
6. Select the area, measurement site, or route you want to monitor
7. Submit the configuration and reload the browser once

You can add multiple entries. For example, you can monitor incidents around home, road conditions across a county, one traffic-flow site, and several travel-time routes at the same time.

### Entry types

| Entry type | What it monitors | Scope or selection | Sensors | Update interval |
| --- | --- | --- | --- | --- |
| **Trafikhändelser** | Current traffic incidents | Coordinate and radius, counties, or all Sweden | Up to 6 | 5 minutes |
| **Väglag** | Assessed road conditions by road section | Coordinate and radius, counties, or all Sweden | 2 | 10 minutes |
| **Trafikflöde** | Vehicle flow and speed at one measurement site and direction | Nearby sites or sites in one county | 3 | 1 minute |
| **Restid på rutt** | Travel time on one predefined Trafikverket route | Route catalog area and route | 3 | 1 minute |

### Change an existing entry

Use **Reconfigure** on the integration entry to change its area, road filter, measurement site, or route. Use **Options** to rename an entry or adjust options that do not replace its selected data source.

Polling intervals are controlled by the integration and cannot be configured by the user.

## Traffic incidents

A **Trafikhändelser** entry creates one sensor for each selected Trafikverket message category.

### Incident sensors

| Sensor | State | Purpose |
| --- | --- | --- |
| Important traffic information | Number | Safety-critical or widely relevant traffic information |
| Obstacle | Number | Objects, stopped vehicles, or other road obstacles |
| Accident | Number | Active reported accidents |
| Restriction | Number | Current traffic restrictions |
| Traffic message | Number | General traffic messages |
| Roadworks | Number | Active roadworks |

The state is the number of visible events in that category. Dismissed events are excluded from the state.

**Attributes**

| Attribute | Type | Description |
| --- | --- | --- |
| `events` | list | Event details exposed to cards and automations |
| `events_total` | number | All matching events before dismissals |
| `events_visible` | number | Matching events after dismissals |
| `dismissed_count` | number | Events currently dismissed |
| `entry_id` | string | Config-entry identifier used by dismiss and restore actions |
| `filter_mode` | string | Active coordinate, county, or Sweden-wide scope |
| `filter_roads` | list | Active road filters |
| `max_items` | number | Maximum number of event objects stored in `events` |
| `last_modified` | datetime | Latest source modification time |

### Incident filtering

| Option | What it does |
| --- | --- |
| **Coordinate and radius** | Includes incidents within the selected radius |
| **Counties / all Sweden** | Includes incidents affecting the selected counties |
| **Road filter** | Narrows results by road number or road name |
| **Message types** | Selects which category sensors the entry creates |
| **Selection / sorting** | Prioritizes relevance, distance, or newest reports |
| **Max items in attributes** | Limits the detailed objects stored in each sensor's `events` attribute |
| **Bypass road filter for safety-related messages** | Allows Trafikverket safety-related messages through even when they do not match the road filter |

Road numbers match exactly. A filter for `84` does not include road `848`. Add a trailing wildcard for prefix matching, such as `84*`. Spaces are normalized, so `E45` matches `E 45`. Road names use case-insensitive partial matching.

**Viktig trafikinformation** always bypasses the road filter. Other safety-related messages bypass it only when **Bypass road filter for safety-related messages** is enabled.

If **Max items in attributes** is `0`, the sensor state still reports the correct count, but the `events` list remains empty. Use a positive value when a dashboard card or automation needs event details.

## Road conditions

A **Väglag** entry uses Trafikverket's section-level road-condition assessments. It does not duplicate Home Assistant's native [Trafikverket Weather Station](https://www.home-assistant.io/integrations/trafikverket_weatherstation/) or [Trafikverket Camera](https://www.home-assistant.io/integrations/trafikverket_camera/) integrations.

### Road-condition sensors

| Sensor | State | Purpose |
| --- | --- | --- |
| Road condition | Enum | Worst current condition in the selected area |
| Hazardous road sections | Number | Sections with a condition above normal |

The primary sensor uses these states:

| State | Meaning |
| --- | --- |
| `no_data` | The request succeeded, but no matching road-condition records were returned |
| `normal` | All matching sections report normal conditions |
| `difficult` | At least one section reports difficult conditions or a risk |
| `very_difficult` | At least one section reports very difficult conditions |
| `ice_snow` | At least one section reports ice or snow conditions |
| `unknown` | Trafikverket returned a condition that could not be classified |

**Attributes**

| Attribute | Type | Description |
| --- | --- | --- |
| `conditions_total` | number | All matching road sections |
| `hazardous_sections` | number | Matching sections above normal |
| `conditions` | list | Detailed road-section records available to the card |
| `last_modified` | datetime | Latest source modification time |
| `filter_mode` | string | Active coordinate, county, or Sweden-wide scope |
| `filter_roads` | list | Active road filters |

Each item in `conditions` can contain road and location text, condition code and text, warnings, causes, maintenance measures, active period, distance, and WGS84 geometry.

**Max items in attributes** controls how many detailed sections are stored in `conditions`. A value of `0` keeps the detailed list empty while the sensor states and counts remain available.

## Traffic flow

A **Trafikflöde** entry combines nearby lane detectors that belong to the same measurement site and direction.

### Select a measurement site

1. Choose **Nearby measurement sites** to search around a position and radius, or **Measurement sites in one county**
2. Select a site and direction
3. Optionally give the entry a custom name

Use **Reconfigure** later to select a different site or direction.

### Traffic-flow sensors

| Sensor | State | Purpose |
| --- | --- | --- |
| Traffic flow | vehicles/h | Total current flow across usable lane detectors |
| Average speed | km/h | Flow-weighted average speed across usable detectors |
| Data quality | Enum | Worst current source quality or freshness for the selected site |

The quality sensor uses these states:

| State | Meaning |
| --- | --- |
| `no_data` | No measurements were returned for the selected site |
| `good` | Current measurements have good source quality |
| `degraded` | At least one usable measurement has degraded quality |
| `bad` | Source data is marked bad |
| `stale` | Measurements are older than five minutes |
| `unknown` | Measurement quality could not be determined |

Measurements marked `bad`, older than five minutes, or of unknown quality are excluded from the numeric flow and speed values. `degraded` measurements remain usable. If no usable measurements remain, flow and speed are `unknown` while the quality sensor explains why.

**Attributes**

| Attribute | Type | Description |
| --- | --- | --- |
| `site_ids` | list | Trafikverket detector identifiers combined by the entry |
| `site_label` | string | Selected location and direction |
| `latitude` / `longitude` | number | Measurement-site position |
| `measurement_time` | datetime | Time of the source measurement |
| `data_age_minutes` | number | Age of the newest usable data |
| `data_quality` | string | Current aggregate quality |
| `valid_measurement_count` | number | Detectors included in the numeric values |
| `total_measurement_count` | number | Detectors returned by Trafikverket |
| `measurements` | list | Per-lane details on the Traffic flow sensor |

## Travel-time routes

A **Restid på rutt** entry monitors one predefined Trafikverket route. Route coverage is concentrated in Stockholm, with smaller coverage in Västra Götaland and Skåne.

### Select a route

1. Choose a route catalog area
2. Select one of the returned routes
3. Optionally give the entry a custom name

Use **Reconfigure** to replace the selected route.

### Route sensors

| Sensor | State | Purpose |
| --- | --- | --- |
| Travel time | minutes | Current travel time |
| Delay | minutes | Signed difference from free-flow travel time |
| Traffic status | Enum | Current route status, commonly `freeflow`, `heavy`, or `congested` |

**Attributes**

| Attribute | Type | Description |
| --- | --- | --- |
| `route_id` | string | Stable Trafikverket route identifier |
| `route_name` | string | Trafikverket route name |
| `speed_kmh` | number | Current route speed |
| `length_m` | number | Route length |
| `free_flow_time_min` | number | Free-flow travel time |
| `delay_min` | number | Signed delay from free-flow time |
| `delay_percent` | number | Delay as a percentage of free-flow time |
| `measure_time` | datetime | Source measurement time |
| `modified_time` | datetime | Source modification time |
| `traffic_status` | string | Current source status |
| `geometry_wgs84` | string | Route geometry used by the route card |

## Dashboard cards

The bundled JavaScript module registers five cards. Each card can be added and edited through the dashboard UI.

1. Open a dashboard
2. Select **Edit dashboard**
3. Select **Add card**
4. Search for **Trafikinfo SE**
5. Select the card that matches your entry type

| UI name | Manual card type | Use |
| --- | --- | --- |
| Trafikinfo SE – Händelser (Olycka/Hinder/Vägarbete/Restriktion) | `custom:trafikinfo-se-alert-card` | Accidents, obstacles, roadworks, restrictions, and traffic messages |
| Trafikinfo SE – Viktig trafikinformation | `custom:trafikinfo-se-viktig-trafikinformation-card` | Focused view for important traffic information |
| Trafikinfo SE – Väglag | `custom:trafikinfo-se-road-condition-card` | Road-condition status, section details, and optional map |
| Trafikinfo SE – Trafikflöde | `custom:trafikinfo-se-traffic-flow-card` | Flow, speed, data quality, and optional lane details |
| Trafikinfo SE – Restid på rutt | `custom:trafikinfo-se-route-card` | One or more routes with optional shared map |

### Road-condition normal status

The road-condition card hides individual normal sections by default. When the sensor confirms normal conditions and reports no hazardous sections, the card shows a green **Normal road conditions** status with the number of checked sections.

- **Show normal status when no hazards are found** controls the positive summary
- **Show individual normal road sections** controls whether code `1` sections are listed
- The card's **Max items** option limits items already present in the sensor's `conditions` attribute; `0` means all available items

### Traffic-flow card

Select the Traffic flow, Average speed, and Data quality entities from the same integration entry. The card uses explicit entity selections so renamed entity IDs remain predictable.

Enable **Show lane details** to display individual detector flow, speed, and quality. Use native History graph or Statistics graph cards for historical charts.

### Route card

The route card accepts one or more Travel time sensors. It can show current travel time, delay, status, update time, and all selected route geometries on one map.

<details>
  <summary>Manual YAML examples</summary>

Replace every placeholder entity ID with an entity from your Home Assistant instance.

```yaml
# Traffic incidents
type: custom:trafikinfo-se-alert-card
entity: sensor.replace_with_accident
```

```yaml
# Road conditions
type: custom:trafikinfo-se-road-condition-card
entity: sensor.replace_with_road_condition
show_normal_status: true
show_normal: false
show_details: true
show_map: false
```

```yaml
# Traffic flow
type: custom:trafikinfo-se-traffic-flow-card
flow_entity: sensor.replace_with_traffic_flow
speed_entity: sensor.replace_with_average_speed
quality_entity: sensor.replace_with_data_quality
show_lanes: false
show_updated: true
severity_background: true
```

```yaml
# Travel-time routes
type: custom:trafikinfo-se-route-card
entities:
  - sensor.replace_with_route_travel_time
show_map: true
```

</details>

### Map configuration

The incident, road-condition, and route cards use OpenStreetMap by default. Each card editor provides the same advanced tile settings:

| Option | Description |
| --- | --- |
| **Custom map tile URL** | HTTPS or same-origin URL containing `{z}`, `{x}`, and `{y}` |
| **Custom map tile attribution** | Attribution required by the selected provider |
| **Map tile maximum zoom** | Highest supported zoom level, from `0` to `22`; default `18` |

Provide both a custom tile URL and attribution, or leave both empty to use OpenStreetMap.

## Automations and notifications

### Home Assistant events

The integration publishes one event for each new or updated accident or obstacle. A road-condition entry publishes events only for hazardous sections.

| Event type | Published when |
| --- | --- |
| `trafikinfo_se_olycka_incident` | An accident is added or updated |
| `trafikinfo_se_hinder_incident` | An obstacle is added or updated |
| `trafikinfo_se_road_condition` | A hazardous road section is added or updated |

The first successful update establishes a baseline and does not publish existing records as new events. Incident payloads include the config entry, entity, change type, source record, and `received_at`.

### Notification blueprint

The bundled Swedish blueprint creates notifications for new or updated accidents and obstacles. It supports Companion App devices, additional notify targets, source-entity filtering, road filters, severity filters, and configurable title and message fields.

[![Import the Trafikinfo SE notification blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FNicxe%2Fhomeassistant-trafikinfo-se%2Fblob%2Fmain%2Fblueprints%2Ftrafikinfo_se_notis_olycka_hinder.yaml)

### Dismiss and restore actions

| Action | Purpose |
| --- | --- |
| `trafikinfo_se.dismiss_event` | Hides one event permanently or until its source data changes |
| `trafikinfo_se.restore_event` | Restores one dismissed event |
| `trafikinfo_se.restore_all_events` | Restores every dismissed event for one integration entry |

The visual incident cards can call these actions for you. Manual calls use the `entry_id` and `event_key` attributes exposed by the incident sensor.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| The integration is not found | Confirm that `config/custom_components/trafikinfo_se/manifest.json` exists, then restart Home Assistant |
| A dashboard card is not available | Restart Home Assistant after the update and reload the browser |
| A card still uses an old layout | Hard-refresh the browser and confirm that the Lovelace resource URL contains `?v=...` |
| A sensor reports `no_data` | The API request succeeded, but the selected scope returned no matching records |
| Entities are unavailable | Check the network connection and Trafikverket availability; the integration retries on its next fixed update |
| Home Assistant requests reauthentication | Replace the rejected API key in the reauthentication flow |
| An incident count is nonzero but the card is empty | Set **Max items in attributes** to a positive value so event details are exposed |
| A road-condition count is available but no sections are listed | Set **Max items in attributes** to a positive value; the green normal summary still works from the counts |
| Road `84` does not include `848` | This is intentional exact matching; use `84*` when you want a prefix |
| No traffic-flow sites are found | Increase the radius or select a different county |
| No travel-time routes are found | Select another route catalog area; Trafikverket route coverage varies by region |

### Manual dashboard resource fallback

Normally the integration manages the resource automatically. If the card module is still missing:

1. Open **Settings > Dashboards > Resources**
2. Add `/local/trafikinfo-se-alert-card.js`
3. Select **JavaScript Module**
4. Reload the browser

## Data source and update intervals

| Data | Trafikverket model | Update interval |
| --- | --- | --- |
| Traffic incidents | `Road.TrafficInfo/Situation` | 5 minutes |
| Road conditions | `Road.TrafficInfo/RoadCondition` | 10 minutes |
| Traffic flow | `Road.TrafficInfo/TrafficFlow` | 1 minute |
| Travel-time routes | `Road.TrafficInfo/TravelTimeRoute` | 1 minute |

An empty successful response becomes `no_data` where the entity supports that state. Temporary network, timeout, and Trafikverket API failures make the affected entities unavailable until the next successful update. A rejected API key starts Home Assistant's reauthentication flow.

The integration does not log your API key. All entities include attribution to Trafikverket.

Trafikverket documents the source models in its data portal:

- [Situation](https://data.trafikverket.se/documentation/datacache/data-model?namespace=Road.TrafficInfo&collection=Situation)
- [RoadCondition](https://data.trafikverket.se/documentation/datacache/data-model?namespace=Road.TrafficInfo&collection=RoadCondition)
- [TrafficFlow](https://data.trafikverket.se/documentation/datacache/data-model?namespace=Road.TrafficInfo&collection=TrafficFlow)
- [TravelTimeRoute](https://data.trafikverket.se/documentation/datacache/data-model?namespace=Road.TrafficInfo&collection=TravelTimeRoute)

## Migration and releases

If you previously installed the standalone `Nicxe/homeassistant-trafikinfo-se-card` repository, follow [MIGRATION.md](./MIGRATION.md). Existing Lovelace card configurations can remain unchanged.

Each GitHub release publishes `trafikinfo_se.zip`. The integration and bundled cards use one shared version.

Use the [issue tracker](https://github.com/Nicxe/homeassistant-trafikinfo-se/issues) for reproducible bugs and feature requests.

## Screenshots

![Trafikinfo SE incident card with event details](https://github.com/user-attachments/assets/b48598dd-d136-4c77-851f-8e4dea6f86df)

![Trafikinfo SE alert card with a traffic event](https://github.com/user-attachments/assets/af609e0f-ca1e-4445-bb04-9cf681b1f0fb)

![Trafikinfo SE dashboard card overview](https://github.com/user-attachments/assets/95d61f2b-42ce-45ca-bad1-29d844979ee5)

## License

See [LICENSE](./LICENSE).
