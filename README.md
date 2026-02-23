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
   - `Trafikinfo SE – Viktig trafikinformation`

You can also use the manual card types:
- `custom:trafikinfo-se-alert-card`
- `custom:trafikinfo-se-viktig-trafikinformation-card`

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

## Automation triggers (event bus)
For sensors **Hinder** and **Olycka**, the integration emits one event per new or updated incident:
- `trafikinfo_se_hinder_incident`
- `trafikinfo_se_olycka_incident`

Each event includes fields such as `incident_key`, `change_type`, `message_type`, `incident`, and `received_at`.

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
