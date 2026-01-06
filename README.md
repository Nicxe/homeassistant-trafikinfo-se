# Trafikinfo SE

Retrieve trafic information for Swedish roads from [Trafikverket](https://www.trafikverket.se/) to Home Assistant

## Prerequisites
Please click [here](https://data.trafikverket.se/home) and register to obtain the API key.


## Installation
To install the Trafikinfo SE integration to your Home Assistant instance using [HACS](https://www.hacs.xyz/)

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

### Entities provided by the integration 
* Olyckor
* Hinder
* Viktig trafikinformation
* Restrektioner
* Trafikmeddelande
* Vägarbete


