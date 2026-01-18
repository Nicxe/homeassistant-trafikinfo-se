## Modernize integration to follow Home Assistant best practices

Updated to follow modern Home Assistant standards for improved stability and better error messages. Icon caching now runs in the background to speed up startup. Note: Entity IDs will change to include `trafikinfo_se_` prefix (e.g., `sensor.trafikinfo_se_hinder`), but Home Assistant will automatically update most references.
