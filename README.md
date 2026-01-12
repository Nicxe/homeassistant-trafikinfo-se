# Trafikinfo SE
[![Buy me a Coffee](https://img.shields.io/badge/Support-Buy%20me%20a%20coffee-fdd734?logo=buy-me-a-coffee)](https://www.buymeacoffee.com/NiklasV) ![GitHub Release](https://img.shields.io/github/v/release/nicxe/homeassistant-trafikinfo-se) ![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/Nicxe/homeassistant-trafikinfo-se/total) ![GitHub Downloads (all assets, latest release)](https://img.shields.io/github/downloads/nicxe/homeassistant-trafikinfo-se/latest/total)

## Overview
Retrieve trafic information for Swedish roads from [Trafikverket](https://www.trafikverket.se/) to Home Assistant

There is also a dashboard card specifically for this integration, which can be found here: [Trafikinfo SE - Alert Card](https://github.com/Nicxe/homeassistant-trafikinfo-se-card)


## Prerequisites
Please click [here](https://data.trafikverket.se/home) and register to obtain the API key.


## Installation
### With HACS (Recommended)

The easiest way to install **Trafikinfo SE** is via **[HACS (Home Assistant Community Store)](https://hacs.xyz/)**

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Nicxe&repository=homeassistant-trafikinfo-se&category=integration)

or

1. Click on the three dots in the top right corner of the HACS overview menu.
2. Select **Custom repositories**.
3. Add the repository URL: `https://github.com/Nicxe/homeassistant-trafikinfo-se`.
4. Select type: **Integration**.
5. Click the **ADD** button.

<details>
<summary>Without HACS</summary>

1. Download the latest release of the Trafikinfo SE integration from **[GitHub Releases](https://github.com/Nicxe/homeassistant-trafikinfo-se/releases)**.
2. Extract the downloaded files and place the `trafikinfo_se` folder in your Home Assistant `custom_components` directory (usually located in the `config/custom_components` directory).
3. Restart your Home Assistant instance to load the new integration.

</details>



## Configuration
To add the Trafikinfo SE integration to your Home Assistant instance, use this My button:

<p>
    <a href="https://my.home-assistant.io/redirect/config_flow_start?domain=trafikinfo_se" class="my badge" target="_blank">
        <img src="https://my.home-assistant.io/badges/config_flow_start.svg">
    </a>
</p>

<details>
<summary>Manual Configuration</summary>

If the button above does not work, you can also perform the following steps manually:

1. Browse to your Home Assistant instance.
2. Go to **Settings > Devices & Services**.
3. In the bottom right corner, select the **Add Integration** button.
4. From the list, select **Trafikinfo SE**.
5. Follow the on-screen instructions to complete the setup.

</details>


## Potential use cases 

* Get notified when an accident, obstacle, or restriction affects your usual commute.
* Stay ahead of roadworks and major traffic disruptions, and adjust plans before you leave home.
* Create simple dashboards and status indicators that summarize current traffic conditions in your area at a glance.

## Entities provided by the integration 
* Olyckor
* Hinder
* Viktig trafikinformation
* Restrektioner
* Trafikmeddelande
* Vägarbete


## Automation triggers (event bus)

For the sensors **Hinder** and **Olycka**, the integration publishes **one event per new/changed incident**. This makes it easy to trigger automations/notifications without having to loop over lists.

- **Hinder**: `trafikinfo_se_hinder_incident`
- **Olycka**: `trafikinfo_se_olycka_incident`

### Event payload

Each per-incident event includes (among others):
- **`incident_key`**: Typically the `deviation_id` (or `situation_id` fallback)
- **`change_type`**: `"added"` or `"updated"`
- **`message_type`**: `"Hinder"` or `"Olycka"`
- **`entry_id`**, **`entry_title`**, **`entity_id`**
- **`incident`**: A single incident dict (same shape as items in the `events` list)
- **`received_at`**: ISO timestamp when the event was emitted

<br>

**Complete event example**
```yaml
event_type: trafikinfo_se_olycka_incident
data:
  entry_id: 01KEHNFFX2FZZJ9NYKC4FCJN2E
  entry_title: Trafikinfo SE
  entity_id: sensor.trafikinfo_se_olycka
  message_type: Olycka
  incident_key: SE_STA_TRISSID_1_19020394
  change_type: added
  received_at: "2026-01-12T08:29:24+00:00"
  incident:
    situation_id: GUID09b6b550-171e-41b4-a84e-653bcb79d672
    deviation_id: SE_STA_TRISSID_1_19020394
    icon_id: roadAccident
    icon_url: >-
      https://api.trafikinfo.trafikverket.se/v2/icons/data/road.infrastructure.icon/roadAccident
    message_type: Olycka
    message_type_value: Accident
    header: null
    message: >-
      Personbil som ligger i diket, blockerar hela vägbanan. Räddningstjänst på
      väg.
    severity_code: 4
    severity_text: Stor påverkan
    road_number: Väg 1753
    road_name: Ödenäsvägen
    county_no:
      - 14
    affected_direction: Båda riktningarna
    affected_direction_value: BothDirections
    start_time: "2026-01-12T09:18:35+01:00"
    end_time: "2026-01-12T10:00:00+01:00"
    valid_until_further_notice: null
    suspended: null
    location_descriptor: >-
      Väg 1753 från Stockagärde till Edsås båda riktningarna i Västra Götalands
      län (O)
    positional_description: null
    traffic_restriction_type: Körfält blockerade
    temporary_limit: null
    number_of_lanes_restricted: 1
    safety_related_message: null
    weblink: null
    geometry_wgs84: POINT (12.5515845797584 57.8451415462886)
    version_time: "2026-01-12T09:21:21.520000+01:00"
    publication_time: "2026-01-12T09:21:56.991000+01:00"
    modified_time: "2026-01-12T08:21:57.061000+00:00"
    distance_km: 37.36
origin: LOCAL
time_fired: "2026-01-12T08:29:24.697950+00:00"
context:
  id: 01KERN5ZASNQDZ3XEB63S5YS22
  parent_id: null
  user_id: null
```
<br>
<br>

## Usage Screenshots


Using the [Trafikifo SE - Alert Card](https://github.com/Nicxe/homeassistant-trafikinfo-se-card)

<img width="614" height="651" alt="CleanShot 2026-01-07 at 19 21 05" src="https://github.com/user-attachments/assets/b48598dd-d136-4c77-851f-8e4dea6f86df" />

<img width="1157" height="587" alt="trafikinfo-se-alert-card" src="https://github.com/user-attachments/assets/af609e0f-ca1e-4445-bb04-9cf681b1f0fb" />



