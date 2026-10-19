import test from 'node:test';
import assert from 'node:assert/strict';
import { toMinorUnits } from '../src/money.mjs';

test('converts decimal ETB amounts exactly to minor units', () => {
  assert.equal(toMinorUnits('1'), 100);
  assert.equal(toMinorUnits('1.2'), 120);
  assert.equal(toMinorUnits('1.23'), 123);
  assert.equal(toMinorUnits('0.01'), 1);
  assert.equal(toMinorUnits('  42.05  '), 4205);
});

test('allows zero only for optional allocation amounts', () => {
  assert.equal(toMinorUnits('0', true), 0);
  assert.throws(() => toMinorUnits('0'));
});

test('rejects unsupported precision, malformed values, negatives, and unsafe ranges', () => {
  for (const value of ['', '1.234', '-1', '+1', '1e2', 'NaN', '90000000000001']) {
    assert.throws(() => toMinorUnits(value), undefined, `should reject ${JSON.stringify(value)}`);
  }
});
