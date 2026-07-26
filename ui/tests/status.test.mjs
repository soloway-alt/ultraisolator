import assert from 'node:assert/strict';
import test from 'node:test';
import { isMonitoringActive } from '../src/utils/status.mjs';

test('falls back to the legacy running flag when monitoring_active is absent', () => {
  assert.equal(isMonitoringActive({ running: true }), true);
  assert.equal(isMonitoringActive({ running: false }), false);
  assert.equal(isMonitoringActive({}), false);
  assert.equal(isMonitoringActive(undefined), false);
  assert.equal(isMonitoringActive(null), false);
});

test('monitoring_active true wins regardless of running', () => {
  assert.equal(isMonitoringActive({ monitoring_active: true }), true);
  assert.equal(isMonitoringActive({ monitoring_active: true, running: false }), true);
});

test('monitoring_active false wins regardless of running', () => {
  assert.equal(isMonitoringActive({ monitoring_active: false }), false);
  assert.equal(isMonitoringActive({ monitoring_active: false, running: true }), false);
});
