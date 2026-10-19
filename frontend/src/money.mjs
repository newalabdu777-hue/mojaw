// Convert decimal text to minor units without binary floating-point rounding.
// The prototype currently supports currencies with two decimal places.
export function toMinorUnits(raw, allowZero = false) {
  const value = String(raw).trim();
  const match = /^(\d+)(?:\.(\d{1,2}))?$/.exec(value);
  if (!match) throw new Error('Enter an amount with no more than two decimal places.');
  const whole = Number(match[1]);
  const fraction = Number((match[2] || '').padEnd(2, '0'));
  const minor = whole * 100 + fraction;
  if (!Number.isSafeInteger(minor) || minor > 9_000_000_000_000_000) {
    throw new Error('Amount is outside the supported range.');
  }
  if (allowZero ? minor < 0 : minor <= 0) {
    throw new Error('Amount must be greater than zero.');
  }
  return minor;
}
