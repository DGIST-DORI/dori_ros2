export function parseWsUrl(rawUrl) {
  if (typeof rawUrl !== 'string' || rawUrl.trim() === '') return null;

  try {
    const parsed = new URL(rawUrl.trim());
    const protocol = parsed.protocol.replace(':', '');

    return {
      protocol,
      host: parsed.hostname,
      port: parsed.port || defaultPortForProtocol(protocol),
      path: parsed.pathname + parsed.search + parsed.hash,
    };
  } catch {
    return null;
  }
}

function defaultPortForProtocol(protocol) {
  if (protocol === 'ws') return '80';
  if (protocol === 'wss') return '443';
  return '-';
}
