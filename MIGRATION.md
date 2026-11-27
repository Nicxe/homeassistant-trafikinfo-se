# Migration Guide

## Upgrading the bundled dashboard cards

Trafikinfo now installs its dashboard module in `config/www/trafikinfo_se/`, alongside the cached traffic icons. Spook can recognize the directory as dashboard content on its next scan. Existing links to `/local/trafikinfo_se/icons/` continue to work.

- **UI-managed resources.** Restart Home Assistant after the update and reload your browser. The integration updates the existing resource in place.
- **YAML-managed resources.** Change the existing module URL from `/local/trafikinfo-se-alert-card.js` or `/trafikinfo_se-static/trafikinfo-se-alert-card.js` to `/local/trafikinfo_se/trafikinfo-se-alert-card.js`. Keep `type: module`, reload dashboard resources, then refresh the browser.

An older copy at `config/www/trafikinfo-se-alert-card.js` may still serve dashboards that refer to it directly. Future updates go to the new directory.

## Migrating from the separate HACS card

1. Install or update the integration from `Nicxe/homeassistant-trafikinfo-se` in HACS as type **Integration**.
2. Remove `Nicxe/homeassistant-trafikinfo-se-card` from HACS if it is still installed.
3. Keep your existing card configurations and follow the resource instructions above.
4. Hard refresh the browser (or clear frontend cache) after updates.

## Integration users
No change is needed to the integration install flow. Continue using HACS for the integration package.

## Release and rollout process

For maintainers, rollout runs through `dev -> beta -> main`.
After the first merged prerelease, there is a required manual pause where test validation is performed in test-HA before continuing to stable.
