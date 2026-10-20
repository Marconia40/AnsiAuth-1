const ACTIVITY_KEY = 'ansiauth.lastActivity';
const CHANNEL_NAME = 'ansiauth-session';
const BROADCAST_THROTTLE_MS = 1_000;

let _lastActivity = Date.now();
let _lastBroadcast = 0;
let _bc: BroadcastChannel | null = null;

type RemoteLogoutHandler = () => void;
const _remoteLogoutHandlers = new Set<RemoteLogoutHandler>();

type ActivityMessage =
  | { type: 'activity'; ts: number }
  | { type: 'logout' };

function readStoredActivity(): number {
  if (typeof window === 'undefined') return 0;
  try {
    const raw = window.localStorage.getItem(ACTIVITY_KEY);
    return raw ? Number(raw) : 0;
  } catch {
    return 0;
  }
}

export function markActivity(source: 'local' | 'remote' = 'local', ts?: number): void {
  const now = ts ?? Date.now();
  if (now <= _lastActivity) return;
  _lastActivity = now;

  if (source !== 'local' || typeof window === 'undefined') return;
  if (now - _lastBroadcast < BROADCAST_THROTTLE_MS) return;
  _lastBroadcast = now;

  try {
    window.localStorage.setItem(ACTIVITY_KEY, String(now));
  } catch {
  }
  _bc?.postMessage({ type: 'activity', ts: now } satisfies ActivityMessage);
}

export function getLastActivity(): number {
  return _lastActivity;
}

export function initSessionActivity(): () => void {
  if (typeof window === 'undefined') return () => {};

  const stored = readStoredActivity();
  if (stored > _lastActivity) _lastActivity = stored;

  const onMessage = (ev: MessageEvent<ActivityMessage>) => {
    if (ev.data?.type === 'activity') {
      markActivity('remote', ev.data.ts);
    } else if (ev.data?.type === 'logout') {
      _remoteLogoutHandlers.forEach((h) => h());
    }
  };
  const onStorage = (ev: StorageEvent) => {
    if (ev.key === ACTIVITY_KEY && ev.newValue) {
      markActivity('remote', Number(ev.newValue));
    }
  };

  if ('BroadcastChannel' in window && !_bc) {
    _bc = new BroadcastChannel(CHANNEL_NAME);
    _bc.addEventListener('message', onMessage);
  }
  window.addEventListener('storage', onStorage);

  return () => {
    if (_bc) {
      _bc.removeEventListener('message', onMessage);
      _bc.close();
      _bc = null;
    }
    window.removeEventListener('storage', onStorage);
  };
}

export function broadcastLogout(): void {
  if (typeof window === 'undefined') return;
  _bc?.postMessage({ type: 'logout' } satisfies ActivityMessage);
}

export function onRemoteLogout(handler: RemoteLogoutHandler): () => void {
  _remoteLogoutHandlers.add(handler);
  return () => {
    _remoteLogoutHandlers.delete(handler);
  };
}
