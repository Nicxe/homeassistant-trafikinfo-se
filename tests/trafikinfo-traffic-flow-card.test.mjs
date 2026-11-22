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


// This fixture is the integration's normalized contract, not Trafikverket XML.
function baselineComparison(overrides = {}) {
  return {
    status: 'valid',
    flow_reference: 1000,
    speed_reference: 80,
    flow_deviation_percent: 30,
    speed_deviation_percent: -35,
    flow_deviation_absolute: 300,
    speed_deviation_absolute: -28,
    matched_detector_count: 3,
    expected_detector_count: 3,
    ...overrides,
  };
}

function createComparisonCard(comparison = baselineComparison()) {
  const states = trafficFlowStates();
  states[FLOW_ENTITY].state = '1300';
  states[SPEED_ENTITY].state = '52';
  states[FLOW_ENTITY].attributes.baseline_comparison = comparison;
  return createCard(states);
}

function templateText(template) {
  if (Array.isArray(template)) return template.map(templateText).join('');
  if (template && typeof template === 'object' && Array.isArray(template.strings)) {
    return template.strings.map((part, index) => part + templateText(template.values[index])).join('');
  }
  return template === undefined || template === null || typeof template === 'function' ? '' : String(template);
}

test('schema 1.5 state keeps the existing card without reference UI', () => {
  const card = createCard();
  assert.equal(card._trafficFlowData().comparison, null);
  const output = templateText(card.render());
  assert.ok(!output.includes('Historisk referens'));
  assert.ok(!output.includes('Jämförelse saknas'));
  assert.equal(card.getCardSize(), 5);
});

test('card renders backend references and deviations independently of good data quality', () => {
  const card = createComparisonCard();
  const output = templateText(card.render());
  assert.match(output, /Historisk referens/);
  assert.match(output, /30 % över referensen/);
  assert.match(output, /35 % lägre hastighet/);
  assert.match(output, /Bra data/);
  assert.equal(card._trafficFlowData().quality, 'good');
  assert.equal(card.getCardSize(), 6);

  card.hass.locale.language = 'en';
  const english = templateText(card.render());
  assert.match(english, /Historical reference/);
  assert.match(english, /30 % above reference/);
  assert.match(english, /35 % below reference/);
  assert.match(english, /Good data/);
});

test('a reference-only update and a language change each rerender the card', () => {
  const card = createComparisonCard();
  const changed = new Map([['hass', {}]]);
  assert.equal(card.shouldUpdate(changed), true);
  assert.equal(card.shouldUpdate(changed), false);
  card.hass.states[FLOW_ENTITY].attributes.baseline_comparison = baselineComparison({
    flow_reference: 1100,
    flow_deviation_percent: 18.18,
    flow_deviation_absolute: 200,
  });
  assert.equal(card.shouldUpdate(changed), true);
  assert.equal(card.shouldUpdate(changed), false);
  card.hass.locale.language = 'en';
  assert.equal(card.shouldUpdate(changed), true);
});

test('zero references display absolute differences without division or zero-percent fallback', () => {
  const card = createComparisonCard(baselineComparison({
    flow_reference: 0,
    speed_reference: 0,
    flow_deviation_percent: null,
    speed_deviation_percent: null,
    flow_deviation_absolute: 1300,
    speed_deviation_absolute: 52,
  }));
  const output = templateText(card.render());
  assert.match(output, /fordon\/tim över referensen/);
  assert.match(output, /52 km\/h högre hastighet/);
  assert.ok(!output.includes('%'));
});

test('zero current flow permits a flow comparison without inventing a speed reference', () => {
  const card = createComparisonCard(baselineComparison({
    speed_reference: null,
    flow_deviation_percent: -100,
    speed_deviation_percent: null,
    flow_deviation_absolute: -1000,
    speed_deviation_absolute: null,
  }));
  card.hass.states[FLOW_ENTITY].state = '0';
  card.hass.states[SPEED_ENTITY].state = 'unknown';
  assert.equal(card._trafficFlowData().comparison.status, 'valid');
  const output = templateText(card.render());
  assert.match(output, /100 % under referensen/);
  assert.match(output, /Hastighetsjämförelse saknas/);
});

for (const [status, swedish, english] of [
  ['missing_reference', 'referensvärden saknas', 'reference data is missing'],
  ['incomplete', 'ofullständigt underlag', 'incomplete detector coverage'],
  ['invalid_data', 'mätningar eller referensvärden är ogiltiga', 'measurements or reference data are invalid'],
]) {
  test(`comparison status ${status} hides numeric references and has both translations`, () => {
    // Deliberately retain stale numbers to prove a non-valid status never exposes them.
    const card = createComparisonCard(baselineComparison({ status }));
    const output = templateText(card.render());
    assert.ok(output.includes(swedish));
    assert.ok(!output.includes('Historisk referens'));
    assert.ok(!output.includes('30 %'));
    card.hass.locale.language = 'en';
    assert.ok(templateText(card.render()).includes(english));
  });
}

for (const quality of ['bad', 'stale', 'unknown', 'no_data', 'unavailable']) {
  test(`quality ${quality} suppresses a previously valid comparison`, () => {
    const card = createComparisonCard();
    card.hass.states[QUALITY_ENTITY].state = quality;
    assert.equal(card._trafficFlowData().comparison.status, 'invalid_data');
    assert.ok(!templateText(card.render()).includes('Historisk referens'));
  });
}

test('degraded data remains comparable while displaying its data quality', () => {
  const card = createComparisonCard();
  card.hass.states[QUALITY_ENTITY].state = 'degraded';
  assert.equal(card._trafficFlowData().comparison.status, 'valid');
  assert.match(templateText(card.render()), /Nedsatt data/);
});

test('old measurements suppress a comparison even when the quality entity still says good', () => {
  const card = createComparisonCard();
  card.hass.states[FLOW_ENTITY].attributes.data_age_minutes = 6;
  assert.equal(card._trafficFlowData().comparison.status, 'invalid_data');
});

test('missing siblings suppress a comparison from a cached flow entity', () => {
  const card = createComparisonCard();
  delete card.hass.states[SPEED_ENTITY];
  assert.equal(card._trafficFlowData().comparison.status, 'invalid_data');
});

test('incomplete detector coverage cannot appear as a valid traffic deviation', () => {
  const card = createComparisonCard(baselineComparison({ matched_detector_count: 2 }));
  assert.equal(card._trafficFlowData().comparison.status, 'incomplete');
  assert.match(templateText(card.render()), /ofullständigt underlag/);
  assert.ok(!templateText(card.render()).includes('30 %'));
});

for (const [name, malformed] of [
  ['string payload', 'invalid'],
  ['array payload', []],
  ['unknown status', baselineComparison({ status: 'unexpected' })],
  ['NaN reference', baselineComparison({ flow_reference: Number.NaN })],
  ['infinite delta', baselineComparison({ speed_deviation_percent: Infinity })],
  ['numeric string', baselineComparison({ flow_reference: '1000' })],
  ['negative reference', baselineComparison({ speed_reference: -1 })],
  ['missing number', baselineComparison({ flow_deviation_absolute: undefined })],
  ['boolean number', baselineComparison({ flow_reference: false })],
  ['zero detector count', baselineComparison({ expected_detector_count: 0, matched_detector_count: 0 })],
  ['fractional detector count', baselineComparison({ expected_detector_count: 2.5 })],
  ['percentage with zero reference', baselineComparison({ flow_reference: 0 })],
  ['missing percentage with positive reference', baselineComparison({ flow_deviation_percent: null })],
  ['missing reference with speed deviation', baselineComparison({ speed_reference: null })],
  ['missing reference with flow deviation', baselineComparison({ flow_reference: null })],
  ['both references missing despite valid status', baselineComparison({ flow_reference: null, flow_deviation_absolute: null, flow_deviation_percent: null, speed_reference: null, speed_deviation_absolute: null, speed_deviation_percent: null })],
]) {
  test(`malformed baseline: ${name} fails closed`, () => {
    const card = createComparisonCard(malformed);
    assert.equal(card._trafficFlowData().comparison.status, 'invalid_data');
    assert.ok(!templateText(card.render()).includes('Historisk referens'));
  });
}

test('stub configuration ignores prepared reference sensors before the measured entities', () => {
  const states = {
    'sensor.test_reference_speed': {
      state: '80',
      attributes: { unit_of_measurement: 'km/h', comparison_status: 'valid' },
    },
    'sensor.test_reference_flow': {
      state: '1000',
      attributes: { unit_of_measurement: 'vehicles/h', comparison_status: 'valid' },
    },
    ...trafficFlowStates(),
  };
  const config = TrafficFlowCard.getStubConfig({ states }, Object.keys(states));
  assert.equal(config.flow_entity, FLOW_ENTITY);
  assert.equal(config.speed_entity, SPEED_ENTITY);
  assert.equal(config.quality_entity, QUALITY_ENTITY);
});

for (const entity of [SPEED_ENTITY, QUALITY_ENTITY]) {
  test(`comparison rejects a different site on ${entity} without changing current values`, () => {
    const card = createComparisonCard();
    card.hass.states[entity].attributes.site_ids = ['9000'];
    const data = card._trafficFlowData();
    assert.equal(data.comparison.status, 'invalid_data');
    assert.equal(data.flowRate, 1300);
    assert.equal(data.speed, 52);
    assert.equal(data.quality, 'good');
    assert.ok(!templateText(card.render()).includes('Historisk referens'));
  });

  test(`comparison rejects a stale measurement timestamp on ${entity}`, () => {
    const card = createComparisonCard();
    card.hass.states[entity].attributes.measurement_time = '2026-08-26T14:07:00+02:00';
    assert.equal(card._trafficFlowData().comparison.status, 'invalid_data');
  });
}

test('comparison accepts reordered duplicate site IDs and equivalent timezone-qualified timestamps', () => {
  const card = createComparisonCard();
  card.hass.states[SPEED_ENTITY].attributes.site_ids = ['3180', 3179, '3178', '3179'];
  card.hass.states[QUALITY_ENTITY].attributes.site_ids = [' 3179 ', '3180', '3178'];
  card.hass.states[SPEED_ENTITY].attributes.measurement_time = '2026-08-26T12:08:00Z';
  card.hass.states[QUALITY_ENTITY].attributes.measurement_time = '2026-08-26T12:08:00.000+00:00';
  assert.equal(card._trafficFlowData().comparison.status, 'valid');
});

for (const [field, value] of [
  ['site_ids', undefined],
  ['site_ids', []],
  ['site_ids', ['3178', '3179', '']],
  ['measurement_time', undefined],
  ['measurement_time', 'not a timestamp'],
  ['measurement_time', '2026-08-26T12:08:00'],
  ['measurement_time', '2026-99-26T12:08:00Z'],
]) {
  test(`comparison rejects missing or malformed source ${field}: ${JSON.stringify(value)}`, () => {
    const card = createComparisonCard();
    card.hass.states[FLOW_ENTITY].attributes[field] = value;
    assert.equal(card._trafficFlowData().comparison.status, 'invalid_data');
  });
}

test('source mismatch only affects comparison and keeps schema 1.5 behavior', () => {
  const card = createCard();
  card.hass.states[SPEED_ENTITY].attributes.site_ids = ['9000'];
  delete card.hass.states[QUALITY_ENTITY].attributes.measurement_time;
  const data = card._trafficFlowData();
  assert.equal(data.comparison, null);
  assert.equal(data.flowRate, 3180);
  assert.equal(data.speed, 71.05);
  assert.equal(data.quality, 'good');
  assert.ok(!templateText(card.render()).includes('Jämförelse saknas'));
});

test('a sibling timestamp mismatch and recovery rerender the comparison', () => {
  const card = createComparisonCard();
  const changed = new Map([['hass', {}]]);
  assert.equal(card.shouldUpdate(changed), true);
  assert.equal(card.shouldUpdate(changed), false);
  card.hass.states[SPEED_ENTITY].attributes.measurement_time = '2026-08-26T14:07:00+02:00';
  assert.equal(card.shouldUpdate(changed), true);
  assert.equal(card._trafficFlowData().comparison.status, 'invalid_data');
  card.hass.states[SPEED_ENTITY].attributes.measurement_time = '2026-08-26T14:08:00+02:00';
  assert.equal(card.shouldUpdate(changed), true);
  assert.equal(card._trafficFlowData().comparison.status, 'valid');
});


for (const [metric, expectedText, absentText] of [
  ['flow', '30 % över referensen', 'Hastighetsjämförelse saknas'],
  ['speed', '35 % lägre hastighet', 'Flödesjämförelse saknas'],
]) {
  test(`independent ${metric} reference remains usable when the other metric is absent`, () => {
    const other = metric === 'flow' ? 'speed' : 'flow';
    const card = createComparisonCard(baselineComparison({
      [`${other}_reference`]: null,
      [`${other}_deviation_absolute`]: null,
      [`${other}_deviation_percent`]: null,
    }));
    assert.equal(card._trafficFlowData().comparison.status, 'valid');
    const output = templateText(card.render());
    assert.ok(output.includes(expectedText));
    assert.ok(output.includes(absentText));
    assert.ok(output.includes('Historisk referens'));

    card.hass.locale.language = 'en';
    const english = templateText(card.render());
    assert.ok(english.includes(other === 'flow' ? 'Flow comparison unavailable' : 'Speed comparison unavailable'));
  });
}

test('tiny positive reference values and deviations never display as zero', () => {
  const card = createComparisonCard(baselineComparison({
    flow_reference: 0.004,
    flow_deviation_absolute: 1299.996,
    flow_deviation_percent: 32499900,
    speed_reference: 51.999,
    speed_deviation_absolute: 0.001,
    speed_deviation_percent: 0.001923,
  }));
  const output = templateText(card.render());
  assert.match(output, /0,004 fordon\/tim/);
  assert.match(output, /0,00192 % högre hastighet/);
  assert.ok(!output.includes('0 % högre hastighet'));
  card.hass.locale.language = 'en';
  assert.match(templateText(card.render()), /0.004 vehicles\/h/);
  assert.match(templateText(card.render()), /0.00192 % above reference/);
});

test('tiny absolute deviations with zero reference remain positive in the rendered label', () => {
  const card = createComparisonCard(baselineComparison({
    flow_reference: 0,
    flow_deviation_absolute: 0.0000002,
    flow_deviation_percent: null,
  }));
  card.hass.states[FLOW_ENTITY].state = '0.0000002';
  const comparison = card._trafficFlowData().comparison;
  assert.equal(comparison.status, 'valid');
  const label = card._formatFlowDeviation(comparison, 'flow');
  assert.ok(label.startsWith('2'));
  assert.match(label, /fordon\/tim över referensen/);
  assert.ok(!label.startsWith('0 '));
});


for (const [unit, raw, expected] of [
  ['km/h', '52', 52],
  ['mph', '50', 80.4672],
  ['m/s', '20', 72],
  ['kn', '20', 37.04],
  ['ft/s', '100', 109.728],
  ['in/s', '100', 9.144],
  ['m/min', '100', 6],
  ['mm/s', '1000', 3.6],
  [undefined, '52', 52],
]) {
  test(`card normalizes ${unit ?? 'legacy missing unit'} to km/h for comparison`, () => {
    const card = createComparisonCard();
    card.hass.states[SPEED_ENTITY].state = raw;
    card.hass.states[SPEED_ENTITY].attributes.unit_of_measurement = unit;
    const data = card._trafficFlowData();
    assert.ok(Math.abs(data.speed - expected) < 0.000001);
    assert.equal(data.comparison.status, 'valid');
  });
}

test('mph state is displayed in km/h alongside the reference and backend deviation', () => {
  const card = createComparisonCard(baselineComparison({
    speed_reference: 100,
    speed_deviation_absolute: -19.5328,
    speed_deviation_percent: -19.5328,
  }));
  card.hass.states[SPEED_ENTITY].state = '50';
  card.hass.states[SPEED_ENTITY].attributes.unit_of_measurement = 'mph';
  const output = templateText(card.render());
  assert.match(output, /80,5/);
  assert.match(output, /Historisk referens: 100 km\/h/);
  assert.match(output, /19,5 % lägre hastighet/);
});

for (const unit of ['Beaufort', 'unsupported']) {
  test(`unsupported unit ${unit} hides speed comparison but preserves valid flow comparison`, () => {
    const card = createComparisonCard();
    card.hass.states[SPEED_ENTITY].attributes.unit_of_measurement = unit;
    const data = card._trafficFlowData();
    assert.equal(data.speed, null);
    assert.equal(data.comparison.status, 'valid');
    assert.equal(data.comparison.speed_reference, null);
    assert.equal(data.comparison.speed_deviation_percent, null);
    const output = templateText(card.render());
    assert.match(output, /30 % över referensen/);
    assert.match(output, /Hastighetsjämförelse saknas/);
    assert.ok(!output.includes('35 % lägre hastighet'));
  });
}

test('stub configuration recognizes a speed entity converted to mph by Home Assistant', () => {
  const states = trafficFlowStates();
  states[SPEED_ENTITY].attributes.device_class = 'speed';
  states[SPEED_ENTITY].attributes.unit_of_measurement = 'mph';
  const config = TrafficFlowCard.getStubConfig({ states }, Object.keys(states));
  assert.equal(config.speed_entity, SPEED_ENTITY);
});
