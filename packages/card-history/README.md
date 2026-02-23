# Trafikinfo SE - Alert Card

[![Buy me a Coffee](https://img.shields.io/badge/Support-Buy%20me%20a%20coffee-fdd734?logo=buy-me-a-coffee)](https://www.buymeacoffee.com/NiklasV) ![GitHub Release](https://img.shields.io/github/v/release/nicxe/homeassistant-trafikinfo-se-card) ![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/Nicxe/homeassistant-trafikinfo-se-card/total) ![GitHub Downloads (all assets, latest release)](https://img.shields.io/github/downloads/nicxe/homeassistant-trafikinfo-se-card/latest/total)

## Overview

This custom card is designed for the [Trafikinfo SE](https://github.com/Nicxe/homeassistant-trafikinfo-se) integration allowing you to display trafic warnings from the Swedish Transport Administration (Trafikverket) on your Home Assistant dashboards.

## Installation
### With HACS (Recommended)

The easiest way to install **Trafikinfo SE - Alert Card** is via **[HACS (Home Assistant Community Store)](https://hacs.xyz/)**

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Nicxe&repository=homeassistant-trafikinfo-se-card&category=plugin)

or
1. Click on the three dots in the top right corner of the HACS overview menu.
2. Select **Custom repositories**.
3. Add the repository URL: `https://github.com/Nicxe/homeassistant-trafikinfo-se-card`.
4. Set the type to **Dashboard**.
5. Click the **Add** button.
6. Search for **Trafikinfo SE** in HACS and click the **Download** button.

<details>
<summary>Without HACS</summary>

1. Download `trafikinfo-se-alert-card.js` from the [latest release](https://github.com/Nicxe/homeaassistant-trafikinfo-se-card/releases).
2. Copy these files into your `config/www` directory, e.g. `config/www/`.
3. Add a reference to `trafikinfo-se-alert-card.js` in your dashboard. There are two ways to do this:
   - **Using the UI:** Go to _Settings_ → _Dashboards_ → _More Options_ → _Resources_ → _Add Resource_. Set the URL as `/local/trafikinfo-se-alert-card.js` and set the _Resource type_ to `JavaScript Module`.
     **Note:** If you do not see the Resources menu, you need to enable _Advanced Mode_ in your _User Profile_.
   - **Using YAML:** Add the following code to the `lovelace` section of your configuration:
     ```yaml
     resources:
       - url: /local/trafikinfo-se-alert-card.js
         type: module
     ```

</details>
    
## Configuration

The card can be configured using the dashboard UI editor:

1. In the dashboard UI, click on the three dots in the top right corner.
2. Click **Edit Dashboard**.
3. Click the **Plus** button to add a new card.
4. Find **Custom: Trafikinfo SE Alert Card** in the list.

## Usage Screenshots

<img width="1157" height="587" alt="trafikinfo-se-alert-card" src="https://github.com/user-attachments/assets/af609e0f-ca1e-4445-bb04-9cf681b1f0fb" />
