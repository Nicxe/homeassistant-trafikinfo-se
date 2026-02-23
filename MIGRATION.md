# Migration Guide

## Who is this for?
This guide is for users who previously installed the alert card from `Nicxe/homeassistant-trafikinfo-se-card`.

## What changed?
The alert card has moved into `Nicxe/homeassistant-trafikinfo-se` and is now released together with the integration.

## What you need to do
1. Update to the latest integration release from `Nicxe/homeassistant-trafikinfo-se`.
2. Restart Home Assistant so the integration can install or update `config/www/trafikinfo-se-alert-card.js`.
3. Keep your Lovelace resource URL unchanged: `/local/trafikinfo-se-alert-card.js`.
4. Hard refresh the browser (or clear frontend cache) after the update.

## Integration users
No change is needed to the integration install flow. Continue using HACS for the integration package.

## Release and rollout process
For maintainers, rollout runs through `dev -> beta -> main`.
After the first merged prerelease, there is a required manual pause where test validation is performed in test-HA before continuing to stable.
