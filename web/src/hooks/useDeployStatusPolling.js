import { useEffect, useRef } from 'react';
import { useStore } from '../core/store';

const POLL_INTERVAL_MS = 2000;
const POLL_ACTIVE_MS = 500;

export function useDeployStatusPolling() {
  const status = useStore((s) => s.deployStatus?.status ?? 'idle');
  const refreshDeployStatus = useStore((s) => s.refreshDeployStatus);
  const timerRef = useRef(null);

  useEffect(() => {
    let disposed = false;

    const schedule = (ms) => {
      clearTimeout(timerRef.current);
      timerRef.current = setTimeout(async () => {
        if (disposed) return;
        await refreshDeployStatus();
        const nextMs = (useStore.getState().deployStatus?.status ?? 'idle') === 'running'
          ? POLL_ACTIVE_MS
          : POLL_INTERVAL_MS;
        schedule(nextMs);
      }, ms);
    };

    refreshDeployStatus();
    schedule(status === 'running' ? POLL_ACTIVE_MS : POLL_INTERVAL_MS);

    return () => {
      disposed = true;
      clearTimeout(timerRef.current);
    };
  }, [refreshDeployStatus, status]);
}

export default useDeployStatusPolling;
