export function normalizePollLines(lines, { dedupeWithinBatch = true } = {}) {
  if (!Array.isArray(lines) || lines.length === 0) return [];
  if (!dedupeWithinBatch) return [...lines];

  const seenInBatch = new Set();
  const normalized = [];

  for (const line of lines) {
    const key = JSON.stringify(line);
    if (seenInBatch.has(key)) continue;
    seenInBatch.add(key);
    normalized.push(line);
  }

  return normalized;
}
