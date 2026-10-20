import axios from 'axios';
import type { AuthUser } from '@/types/auth';
import { getLastActivity } from '@/lib/sessionActivity';
import type {
  VlanEntry,
  VlanCreate,
  VlanUpdate,
  VlanDelete,
  VlanOperationResult,
  VlanBatchRequest,
} from '@/types/vlan';
import type { Device, DeviceCreate, DeviceUpdate } from '@/types/device';
import type {
  RoleAssignment,
  RoleAssignmentCreate,
  User,
  UserCreate,
  UserUpdate,
} from '@/types/user';
import type { Job, GroupJob } from '@/types/job';
import type { AuditLog } from '@/types/audit';
import type { Site, SiteCreate, SiteUpdate } from '@/types/site';
import type {
  PortAccessVlanUpdateRequest,
  PortAdminStateUpdateRequest,
  PortBatchRequest,
  PortDescriptionClearRequest,
  PortDescriptionUpdateRequest,
  PortListResponse,
  PortOperationResult,
  PortPoeUpdateRequest,
  PortResetRequest,
  PortSetAccessModeRequest,
  PortSetTrunkModeRequest,
  PortStormControlUpdateRequest,
  PortTrunkVlansUpdateRequest,
} from '@/types/port';
import type {
  SVIAclClearRequest,
  SVIAclUpdateRequest,
  SVIAdminStateUpdateRequest,
  SVIBatchRequest,
  SVICreateRequest,
  SVIDeleteRequest,
  SVIDescriptionClearRequest,
  SVIDescriptionUpdateRequest,
  SVIDhcpRelayAddRequest,
  SVIDhcpRelayRemoveRequest,
  SVIIpv4ClearRequest,
  SVIIpv4SecondaryAddRequest,
  SVIIpv4SecondaryRemoveRequest,
  SVIIpv4UpdateRequest,
  SVIIpv6ClearRequest,
  SVIIpv6UpdateRequest,
  SVIListResponse,
  SVIOperationResult,
} from '@/types/svi';
import type { DashboardSummary, DashboardSummaryParams } from '@/types/dashboard';
import type {
  AclCreateRequest,
  AclDeleteRequest,
  AclRuleRemoveRequest,
  ArpTableRead,
  DeviceLogsRead,
  DnsAddRequest,
  DnsRemoveRequest,
  GlobalConfigOperationResult,
  GlobalConfigRead,
  GlobalConfigRunningConfigRead,
  GlobalConfigVersionRead,
  HostnameUpdateRequest,
  LogServerAddRequest,
  LogServerRemoveRequest,
  MacTableRead,
  NtpAddRequest,
  NtpRemoveRequest,
  RouteAddRequest,
  RouteRemoveRequest,
  SnmpUpdateRequest,
} from '@/types/global-config';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

type ApiResponse<T> = {
  success: boolean;
  data: T;
};

let _accessToken: string | null = null;

export function setAccessToken(access: string): void {
  _accessToken = access;
  scheduleProactiveRefresh();
}

export function clearAccessToken(): void {
  _accessToken = null;
  cancelProactiveRefresh();
}

function parseAccessTokenExpiryMs(token: string): number | null {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    return typeof payload.exp === 'number' ? payload.exp * 1000 : null;
  } catch {
    return null;
  }
}

const SESSION_EXPIRED_FLAG = 'ansiauth.sessionExpired';
const SESSION_EXPIRED_REASON = 'ansiauth.sessionExpiredReason';

export type SessionExpiredReason =
  | 'idle_timeout'
  | 'session_absolute_limit'
  | 'replay_detected'
  | 'expired'
  | 'invalid';

let _sessionExpiredHandler: (() => void) | null = null;

export function onSessionExpired(handler: () => void): () => void {
  _sessionExpiredHandler = handler;
  return () => {
    if (_sessionExpiredHandler === handler) _sessionExpiredHandler = null;
  };
}

function notifySessionExpired(reason?: SessionExpiredReason | null): void {
  cancelProactiveRefresh();
  _accessToken = null;
  _elevatedToken = null;
  if (typeof window !== 'undefined') {
    try {
      window.sessionStorage.setItem(SESSION_EXPIRED_FLAG, '1');
      if (reason) {
        window.sessionStorage.setItem(SESSION_EXPIRED_REASON, reason);
      } else {
        window.sessionStorage.removeItem(SESSION_EXPIRED_REASON);
      }
    } catch {
    }
  }
  _sessionExpiredHandler?.();
}

function extractRefreshErrorReason(error: unknown): SessionExpiredReason | null {
  const detail = (error as { response?: { data?: { detail?: unknown; message?: unknown } } })
    ?.response?.data;
  const raw = String(detail?.detail ?? detail?.message ?? '');
  const known: SessionExpiredReason[] = [
    'idle_timeout',
    'session_absolute_limit',
    'replay_detected',
    'expired',
    'invalid',
  ];
  return known.find((code) => raw.includes(code)) ?? null;
}

export function consumeSessionExpiredFlag(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    const flag = window.sessionStorage.getItem(SESSION_EXPIRED_FLAG);
    if (flag === '1') {
      window.sessionStorage.removeItem(SESSION_EXPIRED_FLAG);
      return true;
    }
  } catch {
  }
  return false;
}

export function consumeSessionExpiredReason(): SessionExpiredReason | null {
  if (typeof window === 'undefined') return null;
  try {
    const value = window.sessionStorage.getItem(SESSION_EXPIRED_REASON);
    if (value) {
      window.sessionStorage.removeItem(SESSION_EXPIRED_REASON);
      return value as SessionExpiredReason;
    }
  } catch {
  }
  return null;
}

const client = axios.create({
  baseURL: `${BASE_URL}/api/v1`,
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true,
});

client.interceptors.request.use((config) => {
  if (_accessToken) {
    config.headers.Authorization = `Bearer ${_accessToken}`;
  }
  if (isElevatedTokenValid() && _elevatedToken) {
    config.headers['X-Elevated-Auth'] = _elevatedToken.token;
  }
  return config;
});

let _refreshInFlight: Promise<string> | null = null;

async function refreshAccessToken(): Promise<string> {
  if (_refreshInFlight) return _refreshInFlight;

  _refreshInFlight = (async () => {
    try {
      const { data } = await axios.post<{ access_token: string }>(
        `${BASE_URL}/api/v1/auth/refresh`,
        undefined,
        { withCredentials: true },
      );
      _accessToken = data.access_token;
      scheduleProactiveRefresh();
      return data.access_token;
    } finally {
      _refreshInFlight = null;
    }
  })();

  return _refreshInFlight;
}

let _refreshTimer: ReturnType<typeof setTimeout> | null = null;

const ACTIVITY_STALE_MS = 2 * 60 * 1000;

function scheduleProactiveRefresh(): void {
  cancelProactiveRefresh();
  if (typeof window === 'undefined' || !_accessToken) return;

  const expiryMs = parseAccessTokenExpiryMs(_accessToken);
  if (!expiryMs) return;

  const leadMs = 30_000;
  const minDelay = 5_000;
  const maxDelay = 60 * 60_000;
  const delay = Math.max(minDelay, Math.min(expiryMs - Date.now() - leadMs, maxDelay));

  _refreshTimer = setTimeout(() => {
    if (Date.now() - getLastActivity() > ACTIVITY_STALE_MS) {
      return;
    }
    refreshAccessToken().catch((err) => {
      notifySessionExpired(extractRefreshErrorReason(err));
    });
  }, delay);
}

function cancelProactiveRefresh(): void {
  if (_refreshTimer !== null) {
    clearTimeout(_refreshTimer);
    _refreshTimer = null;
  }
}

const REVALIDATE_MARGIN_MS = 5_000;

function revalidateOnResume(): void {
  if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
  if (!_accessToken) return;

  const expiryMs = parseAccessTokenExpiryMs(_accessToken);
  if (expiryMs === null) return;

  if (expiryMs - Date.now() > REVALIDATE_MARGIN_MS) return;

  refreshAccessToken().catch((err) => {
    notifySessionExpired(extractRefreshErrorReason(err));
  });
}

export function registerSessionRevalidation(): () => void {
  if (typeof window === 'undefined') return () => {};

  window.addEventListener('focus', revalidateOnResume);
  document.addEventListener('visibilitychange', revalidateOnResume);

  return () => {
    window.removeEventListener('focus', revalidateOnResume);
    document.removeEventListener('visibilitychange', revalidateOnResume);
  };
}

client.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;

    if (!original || error.response?.status !== 401) {
      return Promise.reject(error);
    }

    const detail = String(error.response?.data?.detail ?? error.response?.data?.message ?? '');
    if (detail.includes('reauth_required') && !original._reauthed) {
      original._reauthed = true;
      try {
        const elevated = await obtainElevatedToken();
        original.headers = original.headers ?? {};
        original.headers['X-Elevated-Auth'] = elevated;
        return client(original);
      } catch {
        return Promise.reject(error);
      }
    }

    if (original._retry) {
      return Promise.reject(error);
    }

    if (typeof original.url === 'string' && original.url.includes('/auth/refresh')) {
      return Promise.reject(error);
    }

    original._retry = true;

    try {
      const newToken = await refreshAccessToken();
      original.headers = original.headers ?? {};
      original.headers.Authorization = `Bearer ${newToken}`;
      return client(original);
    } catch (refreshErr) {
      notifySessionExpired(extractRefreshErrorReason(refreshErr));
      return Promise.reject(error);
    }
  },
);

async function unwrap<T>(promise: Promise<{ data: ApiResponse<T> }>): Promise<T> {
  const { data } = await promise;
  return data.data;
}

export function extractMessage(error: unknown, fallback: string): string {
  const e = error as {
    response?: {
      data?: {
        message?: string;
        details?: { errors?: Array<{ msg?: string }> };
      };
    };
    message?: string;
  } | null;
  const validationMsg = e?.response?.data?.details?.errors?.[0]?.msg;
  return validationMsg ?? e?.response?.data?.message ?? e?.message ?? fallback;
}

export function parseFieldErrors(error: unknown): Record<string, string> | null {
  const e = error as {
    response?: { data?: { details?: { errors?: Array<{ loc?: unknown[]; msg?: string }> } } };
  } | null;
  const errors = e?.response?.data?.details?.errors;
  if (!errors || errors.length === 0) return null;
  const fields: Record<string, string> = {};
  for (const err of errors) {
    const loc = Array.isArray(err.loc) ? err.loc : [];
    const segments = loc.filter((s) => s !== 'body').map(String);
    const field = segments.length > 0 ? segments.join('.') : null;
    if (!field || !err.msg) continue;
    fields[field] = fields[field] ? `${fields[field]}; ${err.msg}` : err.msg;
  }
  return Object.keys(fields).length > 0 ? fields : null;
}

export async function login(
  username: string,
  password: string,
): Promise<AuthUser> {
  const form = new URLSearchParams({ username, password });

  const { data } = await axios.post<{ access_token: string }>(
    `${BASE_URL}/api/v1/auth/login`,
    form,
    {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      withCredentials: true,
    },
  );

  setAccessToken(data.access_token);

  return parseAuthUser(data.access_token);
}

function parseAuthUser(token: string): AuthUser {
  const payload = JSON.parse(atob(token.split('.')[1]));
  const isSystemAdmin = Boolean(payload.is_system_admin);
  const role = payload.role ?? (isSystemAdmin ? 'admin' : 'observer');
  const id = typeof payload.id === 'number' ? payload.id : undefined;
  const canManageUsers =
    typeof payload.can_manage_users === 'boolean'
      ? payload.can_manage_users
      : isSystemAdmin;
  return {
    id,
    username: payload.sub,
    role,
    is_system_admin: isSystemAdmin,
    can_manage_users: canManageUsers,
  };
}

export async function restoreSession(): Promise<AuthUser | null> {
  try {
    const token = await refreshAccessToken();
    return parseAuthUser(token);
  } catch {
    clearAccessToken();
    return null;
  }
}

export async function logout(): Promise<void> {
  await client.post('/auth/logout').catch(() => {});
  clearAccessToken();
  clearElevatedToken();
  if (typeof window !== 'undefined') {
    try {
      window.sessionStorage.removeItem(SESSION_EXPIRED_FLAG);
      window.sessionStorage.removeItem(SESSION_EXPIRED_REASON);
    } catch {
    }
  }
}

export async function signOutClientIdle(): Promise<void> {
  await client.post('/auth/logout').catch(() => {});
  notifySessionExpired('idle_timeout');
}

export interface ActiveSession {
  session_id: string;
  current: boolean;
  created_at: string;
  last_used_at: string;
  expires_at: string;
  ip_address: string | null;
  user_agent: string | null;
}

export async function listActiveSessions(): Promise<ActiveSession[]> {
  const { data } = await client.get<{ sessions: ActiveSession[] }>('/auth/sessions');
  return data.sessions;
}

export async function revokeOtherSessions(): Promise<number> {
  const { data } = await client.post<{ success: boolean; data: { revoked: number } }>(
    '/auth/sessions/revoke-others',
  );
  return data.data.revoked;
}

interface CachedElevatedToken {
  token: string;
  expiresAtMs: number;
}
let _elevatedToken: CachedElevatedToken | null = null;

const ELEVATED_SAFETY_MS = 30_000;

type ElevatedTokenProvider = () => Promise<string>;
let _elevatedProvider: ElevatedTokenProvider | null = null;

export function registerElevatedTokenProvider(provider: ElevatedTokenProvider): () => void {
  _elevatedProvider = provider;
  return () => {
    if (_elevatedProvider === provider) _elevatedProvider = null;
  };
}

export function clearElevatedToken(): void {
  _elevatedToken = null;
}

function isElevatedTokenValid(): boolean {
  if (_elevatedToken === null) return false;
  return _elevatedToken.expiresAtMs - Date.now() > ELEVATED_SAFETY_MS;
}

function setElevatedToken(token: string, expiresInSeconds: number): void {
  _elevatedToken = {
    token,
    expiresAtMs: Date.now() + expiresInSeconds * 1000,
  };
}

export async function reauth(password: string): Promise<void> {
  const { data } = await client.post<{ elevated_token: string; expires_in: number }>(
    '/auth/reauth',
    { password },
  );
  setElevatedToken(data.elevated_token, data.expires_in);
}

async function obtainElevatedToken(): Promise<string> {
  if (isElevatedTokenValid()) return _elevatedToken!.token;
  if (_elevatedProvider === null) {
    throw new Error('Step-up re-authentication required but no provider registered');
  }
  const token = await _elevatedProvider();
  if (isElevatedTokenValid()) return _elevatedToken!.token;
  return token;
}

export interface SyncedResource<T> {
  data: T;
  synced_at: string | null;
  sync_error: string | null;
  sync_in_progress: boolean;
}

export async function getVlans(device?: string): Promise<VlanEntry[]> {
  const envelope = await unwrap<SyncedResource<VlanEntry[]>>(
    client.get<ApiResponse<SyncedResource<VlanEntry[]>>>('/vlans/', {
      params: device ? { device } : {},
    }),
  );
  return envelope.data;
}

export async function getVlansSynced(device: string): Promise<SyncedResource<VlanEntry[]>> {
  return unwrap<SyncedResource<VlanEntry[]>>(
    client.get<ApiResponse<SyncedResource<VlanEntry[]>>>('/vlans/', {
      params: { device },
    }),
  );
}

export async function refreshDeviceVlans(
  device: string,
): Promise<{ device: string; scope: 'vlans'; task_id: string }> {
  return unwrap<{ device: string; scope: 'vlans'; task_id: string }>(
    client.post<ApiResponse<{ device: string; scope: 'vlans'; task_id: string }>>(
      `/devices/${device}/vlans/refresh`,
    ),
  );
}

export async function createVlan(body: VlanCreate): Promise<VlanOperationResult> {
  const result = await unwrap<VlanOperationResult>(client.post<ApiResponse<VlanOperationResult>>('/vlans/', body));
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function updateVlan(vlanId: number, body: VlanUpdate): Promise<VlanOperationResult> {
  const result = await unwrap<VlanOperationResult>(
    client.patch<ApiResponse<VlanOperationResult>>(`/vlans/${vlanId}`, body),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function deleteVlan(vlanId: number, body: VlanDelete): Promise<VlanOperationResult> {
  const result = await unwrap<VlanOperationResult>(
    client.delete<ApiResponse<VlanOperationResult>>(`/vlans/${vlanId}`, { data: body }),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function batchVlans(body: VlanBatchRequest): Promise<VlanOperationResult> {
  const result = await unwrap<VlanOperationResult>(
    client.post<ApiResponse<VlanOperationResult>>('/vlans/batch', body),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function getPorts(device: string): Promise<PortListResponse> {
  const envelope = await unwrap<SyncedResource<PortListResponse>>(
    client.get<ApiResponse<SyncedResource<PortListResponse>>>(`/devices/${device}/ports/`),
  );
  return envelope.data;
}

export async function getPortsSynced(
  device: string,
): Promise<SyncedResource<PortListResponse>> {
  return unwrap<SyncedResource<PortListResponse>>(
    client.get<ApiResponse<SyncedResource<PortListResponse>>>(`/devices/${device}/ports/`),
  );
}

export async function refreshDevicePorts(
  device: string,
): Promise<{ device: string; scope: 'ports'; task_id: string }> {
  return unwrap<{ device: string; scope: 'ports'; task_id: string }>(
    client.post<ApiResponse<{ device: string; scope: 'ports'; task_id: string }>>(
      `/devices/${device}/ports/refresh`,
    ),
  );
}

export async function updatePortDescription(
  device: string,
  body: PortDescriptionUpdateRequest,
): Promise<PortOperationResult> {
  const result = await unwrap<PortOperationResult>(
    client.patch<ApiResponse<PortOperationResult>>(`/devices/${device}/ports/description`, body),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function clearPortDescription(
  device: string,
  body: PortDescriptionClearRequest,
): Promise<PortOperationResult> {
  const result = await unwrap<PortOperationResult>(
    client.delete<ApiResponse<PortOperationResult>>(`/devices/${device}/ports/description`, { data: body }),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function setPortAdminState(
  device: string,
  body: PortAdminStateUpdateRequest,
): Promise<PortOperationResult> {
  const result = await unwrap<PortOperationResult>(
    client.patch<ApiResponse<PortOperationResult>>(`/devices/${device}/ports/admin-state`, body),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function setPortAccessVlan(
  device: string,
  body: PortAccessVlanUpdateRequest,
): Promise<PortOperationResult> {
  const result = await unwrap<PortOperationResult>(
    client.patch<ApiResponse<PortOperationResult>>(`/devices/${device}/ports/access-vlan`, body),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function setTrunkAllowedVlans(
  device: string,
  body: PortTrunkVlansUpdateRequest,
): Promise<PortOperationResult> {
  const result = await unwrap<PortOperationResult>(
    client.patch<ApiResponse<PortOperationResult>>(`/devices/${device}/ports/trunk-vlans`, body),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function setPortAccessMode(
  device: string,
  body: PortSetAccessModeRequest,
): Promise<PortOperationResult> {
  const result = await unwrap<PortOperationResult>(
    client.post<ApiResponse<PortOperationResult>>(`/devices/${device}/ports/access-mode`, body),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function setPortTrunkMode(
  device: string,
  body: PortSetTrunkModeRequest,
): Promise<PortOperationResult> {
  const result = await unwrap<PortOperationResult>(
    client.post<ApiResponse<PortOperationResult>>(`/devices/${device}/ports/trunk-mode`, body),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function setPortPoe(
  device: string,
  body: PortPoeUpdateRequest,
): Promise<PortOperationResult> {
  const result = await unwrap<PortOperationResult>(
    client.patch<ApiResponse<PortOperationResult>>(`/devices/${device}/ports/poe`, body),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function setPortStormControl(
  device: string,
  body: PortStormControlUpdateRequest,
): Promise<PortOperationResult> {
  const result = await unwrap<PortOperationResult>(
    client.patch<ApiResponse<PortOperationResult>>(`/devices/${device}/ports/storm-control`, body),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function resetPort(
  device: string,
  body: PortResetRequest,
): Promise<PortOperationResult> {
  const result = await unwrap<PortOperationResult>(
    client.post<ApiResponse<PortOperationResult>>(`/devices/${device}/ports/reset`, body),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function saveDeviceConfig(device: string): Promise<PortOperationResult> {
  const result = await unwrap<PortOperationResult>(
    client.post<ApiResponse<PortOperationResult>>(`/devices/${device}/save-config`),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function batchUpdatePorts(
  device: string,
  body: PortBatchRequest,
): Promise<PortOperationResult> {
  const result = await unwrap<PortOperationResult>(
    client.post<ApiResponse<PortOperationResult>>(`/devices/${device}/ports/batch`, body),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function getInterfacesVirtuales(device: string): Promise<SVIListResponse> {
  const envelope = await unwrap<{ data: SVIListResponse }>(
    client.get<ApiResponse<{ data: SVIListResponse }>>(`/devices/${device}/svis/`),
  );
  return envelope.data;
}

export async function getSVIsSynced(
  device: string,
): Promise<SyncedResource<SVIListResponse>> {
  return unwrap<SyncedResource<SVIListResponse>>(
    client.get<ApiResponse<SyncedResource<SVIListResponse>>>(`/devices/${device}/svis/`),
  );
}

export async function refreshDeviceSvis(
  device: string,
): Promise<{ device: string; scope: 'svis'; task_id: string }> {
  return unwrap<{ device: string; scope: 'svis'; task_id: string }>(
    client.post<ApiResponse<{ device: string; scope: 'svis'; task_id: string }>>(
      `/devices/${device}/svis/refresh`,
    ),
  );
}

export async function refreshDeviceSync(
  device: string,
): Promise<{ device: string; scope: 'all'; task_id: string }> {
  return unwrap<{ device: string; scope: 'all'; task_id: string }>(
    client.post<ApiResponse<{ device: string; scope: 'all'; task_id: string }>>(
      `/devices/${device}/sync/refresh`,
    ),
  );
}

export async function createSVI(
  device: string,
  body: SVICreateRequest,
): Promise<SVIOperationResult> {
  const result = await unwrap<SVIOperationResult>(
    client.post<ApiResponse<SVIOperationResult>>(`/devices/${device}/svis/`, body),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function deleteSVI(
  device: string,
  body: SVIDeleteRequest,
): Promise<SVIOperationResult> {
  const result = await unwrap<SVIOperationResult>(
    client.delete<ApiResponse<SVIOperationResult>>(`/devices/${device}/svis/`, { data: body }),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function setSVIAdminState(
  device: string,
  body: SVIAdminStateUpdateRequest,
): Promise<SVIOperationResult> {
  const result = await unwrap<SVIOperationResult>(
    client.patch<ApiResponse<SVIOperationResult>>(`/devices/${device}/svis/admin-state`, body),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function setSVIDescription(
  device: string,
  body: SVIDescriptionUpdateRequest,
): Promise<SVIOperationResult> {
  const result = await unwrap<SVIOperationResult>(
    client.patch<ApiResponse<SVIOperationResult>>(`/devices/${device}/svis/description`, body),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function clearSVIDescription(
  device: string,
  body: SVIDescriptionClearRequest,
): Promise<SVIOperationResult> {
  const result = await unwrap<SVIOperationResult>(
    client.delete<ApiResponse<SVIOperationResult>>(`/devices/${device}/svis/description`, { data: body }),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function setSVIIpv4(
  device: string,
  body: SVIIpv4UpdateRequest,
): Promise<SVIOperationResult> {
  const result = await unwrap<SVIOperationResult>(
    client.patch<ApiResponse<SVIOperationResult>>(`/devices/${device}/svis/ipv4`, body),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function clearSVIIpv4(
  device: string,
  body: SVIIpv4ClearRequest,
): Promise<SVIOperationResult> {
  const result = await unwrap<SVIOperationResult>(
    client.delete<ApiResponse<SVIOperationResult>>(`/devices/${device}/svis/ipv4`, { data: body }),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function setSVIIpv6(
  device: string,
  body: SVIIpv6UpdateRequest,
): Promise<SVIOperationResult> {
  const result = await unwrap<SVIOperationResult>(
    client.patch<ApiResponse<SVIOperationResult>>(`/devices/${device}/svis/ipv6`, body),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function clearSVIIpv6(
  device: string,
  body: SVIIpv6ClearRequest,
): Promise<SVIOperationResult> {
  const result = await unwrap<SVIOperationResult>(
    client.delete<ApiResponse<SVIOperationResult>>(`/devices/${device}/svis/ipv6`, { data: body }),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function setSVIAcl(
  device: string,
  body: SVIAclUpdateRequest,
): Promise<SVIOperationResult> {
  const result = await unwrap<SVIOperationResult>(
    client.patch<ApiResponse<SVIOperationResult>>(`/devices/${device}/svis/acl`, body),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function clearSVIAcl(
  device: string,
  body: SVIAclClearRequest,
): Promise<SVIOperationResult> {
  const result = await unwrap<SVIOperationResult>(
    client.delete<ApiResponse<SVIOperationResult>>(`/devices/${device}/svis/acl`, { data: body }),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function addSVIDhcpRelay(
  device: string,
  body: SVIDhcpRelayAddRequest,
): Promise<SVIOperationResult> {
  const result = await unwrap<SVIOperationResult>(
    client.post<ApiResponse<SVIOperationResult>>(`/devices/${device}/svis/dhcp-relay`, body),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function removeSVIDhcpRelay(
  device: string,
  body: SVIDhcpRelayRemoveRequest,
): Promise<SVIOperationResult> {
  const result = await unwrap<SVIOperationResult>(
    client.delete<ApiResponse<SVIOperationResult>>(`/devices/${device}/svis/dhcp-relay`, { data: body }),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function addSVIIpv4Secondary(
  device: string,
  body: SVIIpv4SecondaryAddRequest,
): Promise<SVIOperationResult> {
  const result = await unwrap<SVIOperationResult>(
    client.post<ApiResponse<SVIOperationResult>>(`/devices/${device}/svis/ipv4-secondary`, body),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function removeSVIIpv4Secondary(
  device: string,
  body: SVIIpv4SecondaryRemoveRequest,
): Promise<SVIOperationResult> {
  const result = await unwrap<SVIOperationResult>(
    client.delete<ApiResponse<SVIOperationResult>>(`/devices/${device}/svis/ipv4-secondary`, { data: body }),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function batchUpdateSvi(
  device: string,
  vlanId: number,
  body: SVIBatchRequest,
): Promise<SVIOperationResult> {
  const result = await unwrap<SVIOperationResult>(
    client.patch<ApiResponse<SVIOperationResult>>(`/devices/${device}/svis/${vlanId}/batch`, body),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function getDevices(): Promise<Device[]> {
  return unwrap(client.get<ApiResponse<Device[]>>('/devices/'));
}

export async function getDevice(name: string): Promise<Device> {
  return unwrap(client.get<ApiResponse<Device>>(`/devices/${name}`));
}

export async function createDevice(body: DeviceCreate) {
  return unwrap(client.post('/devices/', body));
}

export async function updateDevice(name: string, body: DeviceUpdate) {
  return unwrap(client.put(`/devices/${name}`, body));
}

export async function deleteDevice(name: string) {
  return unwrap(client.delete(`/devices/${name}`));
}

export async function moveDevice(
  name: string,
  deviceGroupId: number | null,
): Promise<Device> {
  return unwrap(
    client.post<ApiResponse<Device>>(`/devices/${name}/move`, {
      device_group_id: deviceGroupId,
    }),
  );
}

export async function getJobs(params?: {
  status?: string;
  device?: string;
  site_id?: number;
  from_date?: string;
  to_date?: string;
  page?: number;
  page_size?: number;
}): Promise<{ items: Job[]; total: number }> {
  const data = await unwrap<{ items: Job[]; total: number }>(
    client.get<ApiResponse<{ items: Job[]; total: number }>>('/jobs/', { params }),
  );
  return { items: data.items ?? [], total: data.total ?? 0 };
}

export async function getJob(jobId: string): Promise<Job> {
  return unwrap(client.get<ApiResponse<Job>>(`/jobs/${jobId}`));
}

export async function cancelJob(jobId: string): Promise<{ job_id: string; status: string }> {
  return unwrap(client.post(`/jobs/${jobId}/cancel`));
}

export async function retryJobRollback(
  jobId: string,
): Promise<{ job_id: string; group_job_id: string; status: string; retry_of_job_id: string }> {
  return unwrap(client.post(`/jobs/${jobId}/retry-rollback`));
}

export async function getGroupJob(groupJobId: string): Promise<GroupJob> {
  return unwrap(client.get<ApiResponse<GroupJob>>(`/group-jobs/${groupJobId}`));
}

export async function getDashboardSummary(
  params: DashboardSummaryParams,
): Promise<DashboardSummary> {
  const { includeGlobalConfig, ...rest } = params;
  return unwrap<DashboardSummary>(
    client.get<ApiResponse<DashboardSummary>>('/dashboard/summary', {
      params: { ...rest, include_global_config: includeGlobalConfig || undefined },
    }),
  );
}

export interface DashboardRefreshResult {
  devices_queued: number;
  devices_skipped_fresh?: number;
  devices_skipped_coalesced?: number;
  tasks_dispatched: number;
  global_config_devices_queued?: number;
  global_config_devices_skipped_fresh?: number;
  global_config_devices_skipped_coalesced?: number;
}

export type DashboardRefreshParams = Pick<
  DashboardSummaryParams,
  'scope' | 'id' | 'name' | 'includeGlobalConfig'
>;

export async function refreshDashboardScope(
  params: DashboardRefreshParams,
): Promise<DashboardRefreshResult> {
  const { includeGlobalConfig, ...rest } = params;
  return unwrap<DashboardRefreshResult>(
    client.post<ApiResponse<DashboardRefreshResult>>(
      '/dashboard/refresh',
      undefined,
      { params: { ...rest, include_global_config: includeGlobalConfig || undefined } },
    ),
  );
}

export async function getUsers(): Promise<User[]> {
  const data = await unwrap<{ items: User[]; total: number; page: number; page_size: number }>(
    client.get<ApiResponse<{ items: User[]; total: number; page: number; page_size: number }>>('/users/'),
  );
  return data.items ?? [];
}

export async function createUser(body: UserCreate): Promise<User> {
  return unwrap(client.post<ApiResponse<User>>('/users/', body));
}

export async function updateUser(userId: number, body: UserUpdate) {
  return unwrap(client.put(`/users/${userId}`, body));
}

export async function deleteUser(userId: number) {
  return unwrap(client.delete(`/users/${userId}`));
}

export async function getAuditLogs(params?: {
  user?: string;
  action?: string;
  resource?: string;
  status?: string;
  device_id?: string;
  site_id?: number;
  from_date?: string;
  to_date?: string;
  page?: number;
  page_size?: number;
  skip?: number;
  limit?: number;
}): Promise<{ items: AuditLog[]; total: number }> {
  const data = await unwrap<{ items: AuditLog[]; total: number; page: number; page_size: number }>(
    client.get<ApiResponse<{ items: AuditLog[]; total: number; page: number; page_size: number }>>('/audit/', { params }),
  );
  return { items: data.items ?? [], total: data.total ?? 0 };
}

export interface DeviceGroup {
  id: number;
  name: string;
  description: string | null;
  member_count: number;
  created_at: string;
  site_id: number | null;
  site_name: string | null;
}

export async function getDeviceGroups(): Promise<DeviceGroup[]> {
  return unwrap(client.get<ApiResponse<DeviceGroup[]>>('/device-groups/'));
}

export async function createDeviceGroup(body: {
  name: string;
  description?: string;
  site_id: number;
}): Promise<DeviceGroup> {
  return unwrap(client.post<ApiResponse<DeviceGroup>>('/device-groups/', body));
}

export async function deleteDeviceGroup(groupId: number): Promise<void> {
  return unwrap(client.delete(`/device-groups/${groupId}`));
}

export async function getDeviceGroupDevices(groupId: number): Promise<string[]> {
  const { data } = await client.get(`/device-groups/${groupId}/devices`);
  return Array.isArray(data)
    ? data
    : Array.isArray(data.data)
      ? data.data
      : Array.isArray(data.devices)
        ? data.devices
        : Array.isArray(data.data?.devices)
          ? data.data.devices
          : [];
}

export async function getSites(): Promise<Site[]> {
  return unwrap(client.get<ApiResponse<Site[]>>('/sites/'));
}

export async function getSite(siteId: number): Promise<Site> {
  return unwrap(client.get<ApiResponse<Site>>(`/sites/${siteId}`));
}

export async function createSite(body: SiteCreate): Promise<Site> {
  return unwrap(client.post<ApiResponse<Site>>('/sites/', body));
}

export async function updateSite(siteId: number, body: SiteUpdate): Promise<Site> {
  return unwrap(client.put<ApiResponse<Site>>(`/sites/${siteId}`, body));
}

export async function deleteSite(siteId: number): Promise<void> {
  return unwrap(client.delete(`/sites/${siteId}`));
}

export async function listSiteGroups(siteId: number): Promise<DeviceGroup[]> {
  return unwrap(client.get<ApiResponse<DeviceGroup[]>>(`/sites/${siteId}/groups`));
}

export async function listGrants(userId: number): Promise<RoleAssignment[]> {
  return unwrap(
    client.get<ApiResponse<RoleAssignment[]>>(`/users/${userId}/grants`),
  );
}

export async function grant(
  userId: number,
  body: RoleAssignmentCreate,
): Promise<RoleAssignment> {
  return unwrap(
    client.post<ApiResponse<RoleAssignment>>(`/users/${userId}/grants`, body),
  );
}

export async function revoke(userId: number, grantId: number): Promise<void> {
  await client.delete(`/users/${userId}/grants/${grantId}`);
}

export async function setSystemAdmin(
  userId: number,
  isSystemAdmin: boolean,
): Promise<{ id: number; is_system_admin: boolean }> {
  return unwrap(
    client.put<ApiResponse<{ id: number; is_system_admin: boolean }>>(
      `/users/${userId}/system-admin`,
      { is_system_admin: isSystemAdmin },
    ),
  );
}

export async function getGlobalConfigSynced(
  device: string,
): Promise<SyncedResource<GlobalConfigRead>> {
  return unwrap<SyncedResource<GlobalConfigRead>>(
    client.get<ApiResponse<SyncedResource<GlobalConfigRead>>>(
      `/devices/${device}/global-config/`,
    ),
  );
}

export async function getGlobalConfigVersionSynced(
  device: string,
): Promise<SyncedResource<GlobalConfigVersionRead>> {
  return unwrap<SyncedResource<GlobalConfigVersionRead>>(
    client.get<ApiResponse<SyncedResource<GlobalConfigVersionRead>>>(
      `/devices/${device}/global-config/version`,
    ),
  );
}

export async function getGlobalConfigRunningConfigSynced(
  device: string,
): Promise<SyncedResource<GlobalConfigRunningConfigRead>> {
  return unwrap<SyncedResource<GlobalConfigRunningConfigRead>>(
    client.get<ApiResponse<SyncedResource<GlobalConfigRunningConfigRead>>>(
      `/devices/${device}/global-config/running-config`,
    ),
  );
}

export async function getArpTable(
  device: string,
  include?: string,
): Promise<SyncedResource<ArpTableRead>> {
  return unwrap<SyncedResource<ArpTableRead>>(
    client.get<ApiResponse<SyncedResource<ArpTableRead>>>(
      `/devices/${device}/global-config/arp`,
      { params: include ? { include } : {} },
    ),
  );
}

export async function getMacTable(
  device: string,
  include?: string,
): Promise<SyncedResource<MacTableRead>> {
  return unwrap<SyncedResource<MacTableRead>>(
    client.get<ApiResponse<SyncedResource<MacTableRead>>>(
      `/devices/${device}/global-config/mac`,
      { params: include ? { include } : {} },
    ),
  );
}

export async function searchMacTable(
  device: string,
  include: string,
): Promise<{ job_id: string; group_job_id: string; status: string }> {
  return unwrap<{ job_id: string; group_job_id: string; status: string }>(
    client.post<ApiResponse<{ job_id: string; group_job_id: string; status: string }>>(
      `/devices/${device}/global-config/mac/search`,
      null,
      { params: { include } },
    ),
  );
}

export async function getDeviceLogsSynced(
  device: string,
): Promise<SyncedResource<DeviceLogsRead>> {
  return unwrap<SyncedResource<DeviceLogsRead>>(
    client.get<ApiResponse<SyncedResource<DeviceLogsRead>>>(
      `/devices/${device}/global-config/logs`,
    ),
  );
}

export async function refreshDeviceGlobalConfig(
  device: string,
): Promise<{ device: string; scope: 'global_config'; task_id: string }> {
  return unwrap<{ device: string; scope: 'global_config'; task_id: string }>(
    client.post<ApiResponse<{ device: string; scope: 'global_config'; task_id: string }>>(
      `/devices/${device}/global-config/refresh`,
    ),
  );
}

export async function refreshDeviceArpMac(
  device: string,
): Promise<{ device: string; scope: 'arp_mac'; task_id: string }> {
  return unwrap<{ device: string; scope: 'arp_mac'; task_id: string }>(
    client.post<ApiResponse<{ device: string; scope: 'arp_mac'; task_id: string }>>(
      `/devices/${device}/global-config/arp-mac/refresh`,
    ),
  );
}

export async function refreshDeviceLogs(
  device: string,
): Promise<{ device: string; scope: 'logs'; task_id: string }> {
  return unwrap<{ device: string; scope: 'logs'; task_id: string }>(
    client.post<ApiResponse<{ device: string; scope: 'logs'; task_id: string }>>(
      `/devices/${device}/global-config/logs/refresh`,
    ),
  );
}

export async function setGlobalConfigHostname(
  device: string,
  body: HostnameUpdateRequest,
): Promise<GlobalConfigOperationResult> {
  const result = await unwrap<GlobalConfigOperationResult>(
    client.patch<ApiResponse<GlobalConfigOperationResult>>(
      `/devices/${device}/global-config/hostname`,
      body,
    ),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function setGlobalConfigSnmp(
  device: string,
  body: SnmpUpdateRequest,
): Promise<GlobalConfigOperationResult> {
  const result = await unwrap<GlobalConfigOperationResult>(
    client.patch<ApiResponse<GlobalConfigOperationResult>>(
      `/devices/${device}/global-config/snmp`,
      body,
    ),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function addGlobalConfigRoute(
  device: string,
  body: RouteAddRequest,
): Promise<GlobalConfigOperationResult> {
  const result = await unwrap<GlobalConfigOperationResult>(
    client.post<ApiResponse<GlobalConfigOperationResult>>(
      `/devices/${device}/global-config/routes`,
      body,
    ),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function removeGlobalConfigRoute(
  device: string,
  body: RouteRemoveRequest,
): Promise<GlobalConfigOperationResult> {
  const result = await unwrap<GlobalConfigOperationResult>(
    client.delete<ApiResponse<GlobalConfigOperationResult>>(
      `/devices/${device}/global-config/routes`,
      { data: body },
    ),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function addGlobalConfigNtp(
  device: string,
  body: NtpAddRequest,
): Promise<GlobalConfigOperationResult> {
  const result = await unwrap<GlobalConfigOperationResult>(
    client.post<ApiResponse<GlobalConfigOperationResult>>(
      `/devices/${device}/global-config/ntp`,
      body,
    ),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function removeGlobalConfigNtp(
  device: string,
  body: NtpRemoveRequest,
): Promise<GlobalConfigOperationResult> {
  const result = await unwrap<GlobalConfigOperationResult>(
    client.delete<ApiResponse<GlobalConfigOperationResult>>(
      `/devices/${device}/global-config/ntp`,
      { data: body },
    ),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function addGlobalConfigDns(
  device: string,
  body: DnsAddRequest,
): Promise<GlobalConfigOperationResult> {
  const result = await unwrap<GlobalConfigOperationResult>(
    client.post<ApiResponse<GlobalConfigOperationResult>>(
      `/devices/${device}/global-config/dns`,
      body,
    ),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function removeGlobalConfigDns(
  device: string,
  body: DnsRemoveRequest,
): Promise<GlobalConfigOperationResult> {
  const result = await unwrap<GlobalConfigOperationResult>(
    client.delete<ApiResponse<GlobalConfigOperationResult>>(
      `/devices/${device}/global-config/dns`,
      { data: body },
    ),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function addGlobalConfigLogServer(
  device: string,
  body: LogServerAddRequest,
): Promise<GlobalConfigOperationResult> {
  const result = await unwrap<GlobalConfigOperationResult>(
    client.post<ApiResponse<GlobalConfigOperationResult>>(
      `/devices/${device}/global-config/log-servers`,
      body,
    ),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function removeGlobalConfigLogServer(
  device: string,
  body: LogServerRemoveRequest,
): Promise<GlobalConfigOperationResult> {
  const result = await unwrap<GlobalConfigOperationResult>(
    client.delete<ApiResponse<GlobalConfigOperationResult>>(
      `/devices/${device}/global-config/log-servers`,
      { data: body },
    ),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function createOrUpdateGlobalConfigAcl(
  device: string,
  body: AclCreateRequest,
): Promise<GlobalConfigOperationResult> {
  const result = await unwrap<GlobalConfigOperationResult>(
    client.post<ApiResponse<GlobalConfigOperationResult>>(
      `/devices/${device}/global-config/acls`,
      body,
    ),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function removeGlobalConfigAclRules(
  device: string,
  body: AclRuleRemoveRequest,
): Promise<GlobalConfigOperationResult> {
  const result = await unwrap<GlobalConfigOperationResult>(
    client.delete<ApiResponse<GlobalConfigOperationResult>>(
      `/devices/${device}/global-config/acls/rules`,
      { data: body },
    ),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}

export async function deleteGlobalConfigAcl(
  device: string,
  body: AclDeleteRequest,
): Promise<GlobalConfigOperationResult> {
  const result = await unwrap<GlobalConfigOperationResult>(
    client.delete<ApiResponse<GlobalConfigOperationResult>>(
      `/devices/${device}/global-config/acls`,
      { data: body },
    ),
  );
  return { group_job_id: result.group_job_id, jobs: result.jobs ?? [] };
}
