# Migration Guide

## Who is this for?
This guide is for users who previously installed the alert card from `Nicxe/homeassistant-trafikinfo-se-card`.

## What changed?
The integration remains in `Nicxe/homeassistant-trafikinfo-se`, while the card is distributed as a HACS Dashboard plugin from `Nicxe/homeassistant-trafikinfo-se-card` to preserve normal HACS card behavior.

## What you need to do
1. Install or update the integration from `Nicxe/homeassistant-trafikinfo-se` in HACS as type **Integration**.
2. Install or update the card from `Nicxe/homeassistant-trafikinfo-se-card` in HACS as type **Dashboard**.
3. Let HACS manage the card placement in `www/community/` and resource registration.
4. Hard refresh the browser (or clear frontend cache) after updates.

## Integration users
No change is needed to the integration install flow. Continue using HACS for the integration package.

## Release and rollout process
For maintainers, rollout runs through `dev -> beta -> main`.
After the first merged prerelease, there is a required manual pause where test validation is performed in test-HA before continuing to stable.
