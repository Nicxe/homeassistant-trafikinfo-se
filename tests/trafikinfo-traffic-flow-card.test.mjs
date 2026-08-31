import assert from 'node:assert/strict';
import { copyFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, test } from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

const registeredElements = new Map();
const templateTag = (strings, ...values) => ({ strings, values });

globalThis.window = {
  LitElement: class {},
  litHtml: { html: templateTag, css: templateTag },
  location: {
    href: 'http://homeassistant.local:8123/lovelace/test',
    origin: 'http://homeassistant.local:8123',
  },
  customCards: [],
};
globalThis.customElements = {
  define: (name, elementClass) => registeredElements.set(name, elementClass),
  get: (name) => registeredElements.get(name),
};

const cardUrl = new URL(
  '../custom_components/trafikinfo_se/www/trafikinfo-se-alert-card.js',
  import.meta.url,
);
const testDirectory = await mkdtemp(join(tmpdir(), 'trafikinfo-flow-card-test-'));
const testCardPath = join(testDirectory, 'trafikinfo-se-alert-card.mjs');
await copyFile(fileURLToPath(cardUrl), testCardPath);
after(() => rm(testDirectory, { recursive: true, force: true }));
await import(pathToFileURL(testCardPath).href);

const TrafficFlowCard = registeredElements.get('trafikinfo-se-traffic-flow-card');
const TrafficFlowCardEditor = registeredElements.get('trafikinfo-se-traffic-flow-card-editor');

const FLOW_ENTITY = 'sensor.test_traffic_flow';
const SPEED_ENTITY = 'sensor.test_average_speed';
const QUALITY_ENTITY = 'sensor.test_data_quality';

function trafficFlowStates(overrides = {}) {
  const common = {
    site_ids: ['3178', '3179', '3180'],
    site_label: '0.9 km • södergående • 3 körfält • 3180 fordon/tim',
    measurement_time: '2026-08-26T14:08:00+02:00',
    data_age_minutes: 1.2,
    data_quality: 'good',
    valid_measurement_count: 3,
    total_measurement_count: 3,
  };
  return {
    [FLOW_ENTITY]: {
      state: '3180',
      attributes: {
        ...common,
        unit_of_measurement: 'vehicles/h',
        measurements: [
          {
            site_id: '3178',
            specific_lane: 'lane1',
            vehicle_flow_rate: 1080,
            average_vehicle_speed_kmh: 65.2,
            effective_quality: 'good',
          },
          {
            site_id: '3179',
            specific_lane: 'lane2',
            vehicle_flow_rate: 1500,
            average_vehicle_speed_kmh: 74,
            effective_quality: 'degraded',
          },
        ],
      },
    },
    [SPEED_ENTITY]: {
      state: '71.05',
      attributes: { ...common, unit_of_measurement: 'km/h' },
    },
    [QUALITY_ENTITY]: {
      state: 'good',
      attributes: { ...common },
    },
    ...overrides,
  };
}

function createCard(states = trafficFlowStates()) {
  const card = new TrafficFlowCard();
  card.setConfig({
    flow_entity: FLOW_ENTITY,
    speed_entity: SPEED_ENTITY,
    quality_entity: QUALITY_ENTITY,
    show_lanes: true,
  });
  card.hass = {
    language: 'sv',
    locale: { language: 'sv' },
    states,
  };
  return card;
}

test('traffic-flow card and visual editor are registered', () => {
  assert.ok(TrafficFlowCard);
  assert.ok(TrafficFlowCardEditor);
  assert.ok(window.customCards.some((entry) => entry.type === 'trafikinfo-se-traffic-flow-card'));
});

test('card requires three explicit TrafficFlow entities', () => {
  const card = new TrafficFlowCard();
  assert.throws(
    () => card.setConfig({ flow_entity: FLOW_ENTITY }),
    /flow, speed, and quality entities/,
  );
});

test('stub configuration selects all three entities from the same site', () => {
  const states = trafficFlowStates({
    'sensor.unrelated_speed': {
      state: '88',
      attributes: { site_ids: ['9999'], unit_of_measurement: 'km/h' },
    },
  });
  const config = TrafficFlowCard.getStubConfig(
    { states },
    Object.keys(states),
  );

  assert.equal(config.flow_entity, FLOW_ENTITY);
  assert.equal(config.speed_entity, SPEED_ENTITY);
  assert.equal(config.quality_entity, QUALITY_ENTITY);
});

test('card combines current values and removes stale flow text from the site label', () => {
  const data = createCard()._trafficFlowData();

  assert.equal(data.flowRate, 3180);
  assert.equal(data.speed, 71.05);
  assert.equal(data.quality, 'good');
  assert.equal(data.siteLabel, '0.9 km • södergående • 3 körfält');
  assert.equal(data.validCount, 3);
  assert.equal(data.totalCount, 3);
  assert.equal(data.measurements.length, 2);
});

test('lane detail uses effective quality and localized labels', () => {
  const card = createCard();
  const measurements = card._measurements();

  assert.equal(card._laneName(measurements[0], 0), 'Körfält 1');
  assert.equal(card._normalizeQuality(measurements[1].effective_quality), 'degraded');
  assert.equal(card._qualityLabel('stale'), 'För gammal data');
  assert.equal(card._formatDetectorCount(2, 3), '2 av 3 detektorer');
});

test('missing or unavailable sibling entities produce an unavailable card state', () => {
  const states = trafficFlowStates({
    [QUALITY_ENTITY]: {
      state: 'unavailable',
      attributes: { site_ids: ['3178', '3179', '3180'] },
    },
  });
  const data = createCard(states)._trafficFlowData();

  assert.equal(data.unavailable, true);
  assert.equal(data.quality, 'unavailable');
  assert.equal(createCard(states)._qualityClass(data.quality), 'flow-unavailable');
});

test('lane rows contribute to the estimated card height only when enabled', () => {
  const card = createCard();
  assert.equal(card.getCardSize(), 5);

  card.config.show_lanes = false;
  assert.equal(card.getCardSize(), 3);
});
