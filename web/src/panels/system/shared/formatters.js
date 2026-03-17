export const fmt = (val, suffix = '') => (
  val === null || val === undefined ? 'N/A' : `${val}${suffix}`
);

export const pct = (v) => `${Math.min(100, Math.max(0, v ?? 0))}%`;

export const isWarn = (v, threshold) => (
  v !== null && v !== undefined && v >= threshold
);

export const primaryClass = (v, warnAt) => (
  v == null
    ? 'sys-metric-primary'
    : v >= warnAt
      ? 'sys-metric-primary is-warning'
      : 'sys-metric-primary is-ok'
);

export const valueClass = (v, warnAt) => (
  v == null
    ? 'sys-metric-value'
    : v >= warnAt
      ? 'sys-metric-value is-warning'
      : 'sys-metric-value is-ok'
);

export const hzClass = (hz) => (
  hz == null ? 'hz-none' : hz >= 1 ? 'hz-ok' : 'hz-warn'
);
