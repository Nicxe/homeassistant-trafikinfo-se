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
const testDirectory = await mkdtemp(join(tmpdir(), 'trafikinfo-card-test-'));
const testCardPath = join(testDirectory, 'trafikinfo-se-alert-card.mjs');
await copyFile(fileURLToPath(cardUrl), testCardPath);
after(() => rm(testDirectory, { recursive: true, force: true }));
await import(pathToFileURL(testCardPath).href);

const AlertCard = registeredElements.get('trafikinfo-se-alert-card');
const RoadConditionCard = registeredElements.get('trafikinfo-se-road-condition-card');

function event(roadNumber, roadName) {
  return {
    event_key: `event-${roadNumber}`,
    road_number: roadNumber,
    road_name: roadName,
    severity_code: 2,
  };
}

function visibleRoads(filterRoads, events) {
  const card = new AlertCard();
  card.config = {
    entity: 'sensor.test_accidents',
    filter_roads: filterRoads,
    filter_severities: [],
    preset: 'accident',
  };
  card.hass = {
    states: {
      'sensor.test_accidents': { attributes: { events } },
    },
  };
  card._pendingDismiss = new Set();

  return card._visibleEvents().map((item) => item.road_number);
}

test('plain road numbers use exact matching', () => {
  const events = [
    event('84', 'Väg 84'),
    event('848', 'Vallervägen (Väg 848)'),
    event('E4', 'Europaväg E4'),
    event('E45', 'Europaväg E45'),
  ];

  assert.deepEqual(visibleRoads('84; E4', events), ['84', 'E4']);
});

test('a trailing wildcard enables road-number prefix matching', () => {
  const events = [
    event('71', 'Väg 71'),
    event('712', 'Väg 712'),
    event('713', 'Väg 713'),
    event('715', 'Väg 715'),
    event('72', 'Väg 72'),
  ];

  assert.deepEqual(visibleRoads('Väg 71*', events), ['71', '712', '713', '715']);
});

test('road names keep case-insensitive partial matching', () => {
  const events = [
    event('848', 'Vallervägen (Väg 848)'),
    event('84', 'Landsvägen (Väg 84)'),
  ];

  assert.deepEqual(visibleRoads('VALLER', events), ['848']);
});

test('unsupported wildcard forms do not match', () => {
  const events = [event('711', 'Väg 711'), event('848', 'Vallervägen (Väg 848)')];

  assert.deepEqual(visibleRoads('*, 7*1', events), []);
});

test('road condition card is registered and hides normal sections by default', () => {
  assert.ok(RoadConditionCard);
  const card = new RoadConditionCard();
  card.config = {
    entity: 'sensor.test_road_condition',
    show_normal: false,
    max_items: 0,
  };
  card.hass = {
    states: {
      'sensor.test_road_condition': {
        state: 'ice_snow',
        attributes: {
          conditions: [
            { id: 'normal', state: 'normal', condition_code: 1, road_number: '84' },
            { id: 'snow', state: 'ice_snow', condition_code: 4, road_number: '848' },
          ],
        },
      },
    },
  };

  assert.deepEqual(card._conditionItems().map((item) => item.id), ['snow']);
});

test('road condition card sorts by severity and can show normal sections', () => {
  const card = new RoadConditionCard();
  card.config = {
    entity: 'sensor.test_road_condition',
    show_normal: true,
    max_items: 0,
  };
  card.hass = {
    states: {
      'sensor.test_road_condition': {
        state: 'very_difficult',
        attributes: {
          conditions: [
            { id: 'normal', state: 'normal', condition_code: 1 },
            { id: 'risk', state: 'difficult', condition_code: 2 },
            { id: 'very', state: 'very_difficult', condition_code: 3 },
          ],
        },
      },
    },
  };

  assert.deepEqual(
    card._conditionItems().map((item) => item.id),
    ['very', 'risk', 'normal'],
  );
});
