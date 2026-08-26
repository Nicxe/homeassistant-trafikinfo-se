# Trafikinfo SE
[![Buy me a Coffee](https://img.shields.io/badge/Support-Buy%20me%20a%20coffee-fdd734?logo=buy-me-a-coffee)](https://www.buymeacoffee.com/NiklasV) ![GitHub Release](https://img.shields.io/github/v/release/nicxe/homeassistant-trafikinfo-se) ![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/Nicxe/homeassistant-trafikinfo-se/total) ![GitHub Downloads (all assets, latest release)](https://img.shields.io/github/downloads/nicxe/homeassistant-trafikinfo-se/latest/total)

## Overview
Trafikinfo SE brings real-time Swedish road traffic information from [Trafikverket](https://www.trafikverket.se/) into Home Assistant.

This repository now contains both:
- The Home Assistant integration (`trafikinfo_se`)
- The Lovelace alert card (`trafikinfo-se-alert-card.js`)

## Prerequisites
Register at [Trafikverkets API portal](https://data.trafikverket.se/home) to get your API key.

## Installation
### Integration with HACS (recommended)
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Nicxe&repository=homeassistant-trafikinfo-se&category=integration)

You can also add the repository manually in HACS as type **Integration**.

### Integration without HACS
1. Download `trafikinfo_se.zip` from the [latest release](https://github.com/Nicxe/homeassistant-trafikinfo-se/releases).
2. Extract the archive and place the `trafikinfo_se` folder in `config/custom_components/`.
3. Restart Home Assistant.

### Alert card installation
The alert card is bundled with this integration.

When the integration starts, it automatically:

- syncs the bundled card to `config/www/trafikinfo-se-alert-card.js`
- creates or updates a Lovelace `module` resource at `/local/trafikinfo-se-alert-card.js?v=...` for cache-busting

If you have just installed or updated, reload the browser once to ensure the latest card resource is loaded.

## Card usage
The card can be configured in the dashboard UI editor:

1. Open your dashboard.
2. Select **Edit dashboard**.
3. Add a new card.
4. Search for and select one of:

   - `Trafikinfo SE – Händelser (Olycka/Hinder/Vägarbete/Restriktion)`
   - `Trafikinfo SE – Restid på rutt`
   - `Trafikinfo SE – Väglag`
   - `Trafikinfo SE – Viktig trafikinformation`

You can also use the manual card types:

- `custom:trafikinfo-se-alert-card`
- `custom:trafikinfo-se-route-card`
- `custom:trafikinfo-se-road-condition-card`
- `custom:trafikinfo-se-viktig-trafikinformation-card`

### Map configuration
Maps in the incident, route, and road-condition cards use OpenStreetMap by default and include the required attribution. The same optional tile-provider settings are available in all three card editors:

- **Custom map tile URL**: HTTPS or same-origin URL containing `{z}`, `{x}`, and `{y}`
- **Custom map tile attribution**: attribution required by the selected provider
- **Map tile maximum zoom**: highest supported zoom level, from `0` to `22` (default `18`)

Both a custom tile URL and its attribution must be provided together. Leave these fields empty to use the default OpenStreetMap tiles. A custom provider can be useful when you need different map styling, coverage, availability guarantees, or a self-hosted tile service.

### Manual fallback (if needed)
Normally no manual Lovelace resource setup is required.

If your dashboard does not load the card automatically, add this resource manually:
- URL: `/local/trafikinfo-se-alert-card.js`
- Type: `JavaScript Module`

## Configuration
To add the integration, use this My button:

<p>
  <a href="https://my.home-assistant.io/redirect/config_flow_start?domain=trafikinfo_se" class="my badge" target="_blank">
    <img src="https://my.home-assistant.io/badges/config_flow_start.svg" alt="Add Trafikinfo SE to Home Assistant">
  </a>
</p>

If needed, add it manually via **Settings > Devices & Services > Add Integration**.

## Entities provided by the integration
- Olyckor
- Hinder
- Viktig trafikinformation
- Restriktioner
- Trafikmeddelande
- Vägarbete
- Väglag (worst current condition in the selected area)
- Avvikande vägsträckor (number of sections with a condition code above normal)
- Trafikflöde (combined vehicles per hour at one measurement site)
- Medelhastighet (flow-weighted speed at the selected site)
- Datakvalitet (source quality and freshness for the selected site)

## RoadCondition support (phase 1)
Road conditions are available as a separate setup type called **Väglag**. This uses Trafikverket's `Road.TrafficInfo/RoadCondition` model to show the assessed condition of road sections, including warnings, causes, and reported maintenance measures.

This is deliberately not a copy of Home Assistant's native [Trafikverket Weather Station](https://www.home-assistant.io/integrations/trafikverket_weatherstation/) or [Trafikverket Camera](https://www.home-assistant.io/integrations/trafikverket_camera/) integrations. Those integrations expose measurements and camera images from individual stations. Trafikinfo SE instead reports Trafikverket's current, section-level road-condition assessment.

When adding a Väglag entry, choose one of these scopes:

- a coordinate and radius
- one or more counties, or all of Sweden

An optional road filter can narrow the result further. Numeric road filters are exact, so `84` does not include road `848`. Add a trailing wildcard when a prefix is intended, for example `84*`. Spaces in numbered roads are normalized, so `E45` matches Trafikverket's `E 45`, and a value such as `570` also matches a named road value containing `väg 570`.

The primary road-condition sensor has these stable states:

- `no_data`
- `normal`
- `difficult`
- `very_difficult`
- `ice_snow`
- `unknown`

Its `conditions` attribute contains the matching current road sections, sorted with the most severe condition first. Each item can include road and location text, the Trafikverket condition code and text, warnings, causes, measures, active period, distance, and WGS84 geometry. The integration controls polling at a fixed 10-minute interval to avoid unnecessary API load.

### Road-condition card
Use `custom:trafikinfo-se-road-condition-card` with the primary Väglag sensor. The card hides normal sections by default, sorts visible sections by severity, and can show warnings, causes, measures, distance, active period, and an optional shared map. Enable **Show normal road sections** when you also want code `1` sections listed.

Example:

```yaml
type: custom:trafikinfo-se-road-condition-card
entity: sensor.trafikinfo_se_road_condition_state
show_normal: false
show_details: true
show_map: true
```

### Empty data and errors
An empty but successful API response is reported as `no_data`; it is not treated as a failure. Temporary network, timeout, or Trafikverket API errors make the entities unavailable until the coordinator's next successful retry. A missing or rejected API key starts Home Assistant's authentication recovery flow instead of silently returning empty data. Home Assistant logs include an actionable error without logging the API key.

## TrafficFlow support (phase 2)
Traffic flow is available as a separate setup type called **Trafikflöde**. It uses Trafikverket's `Road.TrafficInfo/TrafficFlow` model and complements the incident and road-condition views with current detector-based traffic volume and speed.

When adding a Trafikflöde entry, find a measurement site in either of these ways:

- choose a position and search radius to list the nearest sites
- choose one county and a reference position to sort that county's sites by distance

The site list combines nearby lane detectors that belong to the same physical location and direction. After a site is selected, the integration stores its actual Trafikverket `SiteId` values and limits every recurring API request to those identifiers. This avoids downloading nationwide flow data every minute. Use **Reconfigure** on the integration entry to select a different site or direction.

Each Trafikflöde entry creates three sensors:

- **Trafikflöde** — total current flow across usable lane detectors, in vehicles per hour
- **Medelhastighet** — flow-weighted average speed across usable lane detectors, in km/h
- **Datakvalitet** — the worst current quality or freshness state reported for the selected site

The quality sensor has the stable states `no_data`, `good`, `degraded`, `bad`, `stale`, and `unknown`. Measurements marked `bad`, older than five minutes, or of unknown quality are not included in the numeric flow or speed values. `degraded` measurements remain usable but are explicitly exposed as degraded. The attributes include measurement time, data age, selected site identifiers, detector counts, and the individual lane measurements. The fixed polling interval is one minute.

An empty successful response is shown as `no_data`. If all returned measurements are unusable, the flow and speed sensors are `unknown` while the quality sensor explains why. Temporary network, timeout, or API failures make the entities unavailable until the next successful update, and a rejected API key starts Home Assistant's authentication recovery flow.

FAS 2 intentionally uses Home Assistant's normal entity and history cards rather than adding another custom card. Add the three entities through the dashboard editor, or replace the placeholder IDs below with the actual entity IDs from your Trafikflöde entry:

```yaml
type: entities
entities:
  - entity: sensor.replace_with_traffic_flow
  - entity: sensor.replace_with_average_speed
  - entity: sensor.replace_with_data_quality
```

For a historical view, add the flow and speed sensors to a History graph or Statistics graph card. The source model is documented in Trafikverket's [TrafficFlow data model](https://data.trafikverket.se/documentation/datacache/data-model?namespace=Road.TrafficInfo&collection=TrafficFlow).

## TravelTimeRoute support
The integration now supports Trafikverket's `TravelTimeRoute` data model as a separate route-focused setup flow within the same integration.

This mode is designed for commute-style monitoring, where the most important questions are how long a route takes right now, how much slower it is than normal, and whether traffic conditions are getting worse.

When you add a route entry, the integration creates route-specific sensors for:
- current travel time
- delay compared with free-flow traffic
- current traffic status

The route data also includes geometry in WGS84, which the route card can use to draw the monitored road segment directly on a map.

## Route card
The route card is available as `custom:trafikinfo-se-route-card`.

It supports both:
- a single route sensor
- multiple route sensors in the same card

When you add multiple route sensors, the card lists them one after another and can show all selected road segments on the same map. Each route line is color-coded from the sensor state so it is easier to scan the traffic situation for a whole area such as Gothenburg.

The route card can show:
- current travel time
- signed delay versus free-flow time
- traffic status
- update time
- a shared map with route lines

The map is optional and intended for the detailed card view.

## Automation triggers (event bus)
For sensors **Hinder** and **Olycka**, the integration emits one event per new or updated incident:

- `trafikinfo_se_hinder_incident`
- `trafikinfo_se_olycka_incident`

Each event includes fields such as `incident_key`, `change_type`, `message_type`, `incident`, and `received_at`.

For a Väglag entry, the integration emits `trafikinfo_se_road_condition` when a hazardous road section is new or its reported condition changes after the initial data load. The event includes the config entry ID, change type, the complete condition item, and `received_at`. The initial load establishes a baseline and does not emit historical conditions as new events.

## Release assets and versioning
Each GitHub release in this repository publishes:
- `trafikinfo_se.zip` for integration installation

The bundled alert card is included inside `trafikinfo_se.zip`.

The project uses one shared version across integration and card.

## Commit conventions for release notes
Use Conventional Commits with component scopes for clear release notes, for example:
- `feat(integration): ...`
- `fix(card): ...`
- `chore(ci): ...`

## Migration from the old card repository
If you previously used `homeassistant-trafikinfo-se-card`, see [MIGRATION.md](./MIGRATION.md).

## Usage screenshots
<img width="614" height="651" alt="trafikinfo example" src="https://github.com/user-attachments/assets/b48598dd-d136-4c77-851f-8e4dea6f86df" />

<img width="1157" height="587" alt="trafikinfo alert card" src="https://github.com/user-attachments/assets/af609e0f-ca1e-4445-bb04-9cf681b1f0fb" />

<img width="578" height="784" alt="CleanShot 2026-03-20 at 15 32 33" src="https://github.com/user-attachments/assets/95d61f2b-42ce-45ca-bad1-29d844979ee5" />
