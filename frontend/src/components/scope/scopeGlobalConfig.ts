'use client';

import { useQuery } from '@tanstack/react-query';
import { getDashboardSummary } from '@/services/api';
import type { DashboardSummary } from '@/types/dashboard';
import type {
  GlobalConfigRouteEntry,
  GlobalConfigScopeDeviceEntry,
} from '@/types/global-config';
import { SYNC_POLL_INTERVAL_MS } from '@/lib/syncPolling';
import { scopeToSummaryParams, type Scope } from './ScopeDashboard';

export function useScopeGlobalConfig(scope: Scope) {
  const query = useQuery<DashboardSummary>({
    queryKey: ['dashboard', 'summary', scope, { includeGlobalConfig: true }],
    queryFn: () => getDashboardSummary({ ...scopeToSummaryParams(scope), includeGlobalConfig: true }),
    refetchInterval: (q) => {
      const data = q.state.data as DashboardSummary | undefined;
      return data?.global_config?.some((d) => d.sync_in_progress) ? SYNC_POLL_INTERVAL_MS : false;
    },
  });

  const entries = query.data?.global_config ?? [];

  return {
    entries,
    isLoading: query.isLoading,
    isError: query.isError,
    refetch: query.refetch,
  };
}

export interface SnmpRow {
  device: string;
  vendor: string | null;
  enabled: boolean | null;
  version: string | null;
  community: string | null;
  permission: string | null;
  trapHosts: string[];
}

export function toSnmpRows(entries: GlobalConfigScopeDeviceEntry[]): SnmpRow[] {
  return entries.map((e) => ({
    device: e.device,
    vendor: e.vendor,
    enabled: e.snmp.enabled,
    version: e.snmp.version,
    community: e.snmp.community,
    permission: e.snmp.permission,
    trapHosts: e.snmp.trap_hosts ?? [],
  }));
}

export interface ServerRow {
  device: string;
  server: string;
  level?: string | null;
}

export function toNtpRows(entries: GlobalConfigScopeDeviceEntry[]): ServerRow[] {
  return entries.flatMap((e) =>
    (e.ntp.servers ?? []).map((server) => ({ device: e.device, server })),
  );
}

export function toDnsRows(entries: GlobalConfigScopeDeviceEntry[]): ServerRow[] {
  return entries.flatMap((e) =>
    (e.dns.servers ?? []).map((server) => ({ device: e.device, server })),
  );
}

export function toLogRows(entries: GlobalConfigScopeDeviceEntry[]): ServerRow[] {
  return entries.flatMap((e) =>
    (e.logging.servers ?? []).map((server) => ({
      device: e.device,
      server,
      level: e.logging.level,
    })),
  );
}

export interface RouteRow {
  device: string;
  destination: string | null;
  nextHop: string | null;
  interface: string | null;
  esGateway: boolean;
}

export function toRouteRows(entries: GlobalConfigScopeDeviceEntry[]): RouteRow[] {
  return entries.flatMap((e) =>
    (e.routes ?? []).map((r: GlobalConfigRouteEntry) => ({
      device: e.device,
      destination: typeof r.destination === 'string' ? r.destination : null,
      nextHop: typeof r.next_hop === 'string' ? r.next_hop : null,
      interface: typeof r.interface === 'string' ? r.interface : null,
      esGateway: r.tipo === 'default-gateway',
    })),
  );
}

export interface AclMatrixCell {
  present: boolean;
  type: string | null;
  ruleCount: number;
  rules: string[];
}

export interface AclMatrixRow {
  name: string;
  perDevice: Record<string, AclMatrixCell>;
}

export function toAclMatrix(entries: GlobalConfigScopeDeviceEntry[]): AclMatrixRow[] {
  const byName = new Map<string, AclMatrixRow>();
  for (const entry of entries) {
    for (const acl of entry.acls ?? []) {
      let row = byName.get(acl.name);
      if (!row) {
        row = { name: acl.name, perDevice: {} };
        byName.set(acl.name, row);
      }
      row.perDevice[entry.device] = {
        present: true,
        type: acl.type,
        ruleCount: acl.rules.length,
        rules: acl.rules,
      };
    }
  }
  return Array.from(byName.values()).sort((a, b) => a.name.localeCompare(b.name));
}
