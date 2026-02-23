# Migration Guide

## Who is this for?
This guide is for users who previously installed the alert card from `Nicxe/homeassistant-trafikinfo-se-card`.

## What changed?
The card is now bundled directly in `Nicxe/homeassistant-trafikinfo-se` and is managed by the integration itself.
The integration syncs the bundled card to `/config/www/trafikinfo-se-alert-card.js` and keeps the Lovelace resource at `/local/trafikinfo-se-alert-card.js?v=...` updated to avoid stale browser cache.

## What you need to do
1. Install or update the integration from `Nicxe/homeassistant-trafikinfo-se` in HACS as type **Integration**.
2. Remove `Nicxe/homeassistant-trafikinfo-se-card` from HACS if it is still installed.
3. Keep existing Lovelace cards as-is. The integration keeps `/local/trafikinfo-se-alert-card.js?v=...` updated automatically.
4. Hard refresh the browser (or clear frontend cache) after updates.

## Integration users
No change is needed to the integration install flow. Continue using HACS for the integration package.

## Release and rollout process
For maintainers, rollout runs through `dev -> beta -> main`.
After the first merged prerelease, there is a required manual pause where test validation is performed in test-HA before continuing to stable.
