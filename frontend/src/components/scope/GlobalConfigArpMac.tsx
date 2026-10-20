'use client';

import { useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  getArpTable,
  getJob,
  getMacTable,
  refreshDeviceArpMac,
  searchMacTable,
  type SyncedResource,
} from '@/services/api';
import type {
  ArpMacEntry,
  ArpTableRead,
  MacTableRead,
} from '@/types/global-config';
import { Panel } from './Panel';
import { RefreshButton } from './RefreshButton';
import { SYNC_POLL_INTERVAL_MS } from '@/lib/syncPolling';

interface Props {
  deviceName: string;
}

const INCLUDE_RE = /^[A-Za-z0-9:./_-]{1,64}$/;

const ARP_COLUMNS = ['ip', 'mac', 'age', 'type', 'interface', 'vlan'] as const;
const MAC_COLUMNS = ['mac', 'vlan', 'type', 'interface'] as const;

export function GlobalConfigArpMac({ deviceName }: Props) {
  const queryClient = useQueryClient();

  const [rawInclude, setRawInclude] = useState('');
  const [debouncedInclude, setDebouncedInclude] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setDebouncedInclude(rawInclude), 300);
    return () => clearTimeout(t);
  }, [rawInclude]);

  const includeValid = rawInclude === '' || INCLUDE_RE.test(rawInclude);
  const includeParam =
    debouncedInclude !== '' && INCLUDE_RE.test(debouncedInclude)
      ? debouncedInclude
      : undefined;

  const arpQuery = useQuery({
    queryKey: ['arp-table', deviceName, includeParam ?? ''],
    queryFn: () => getArpTable(deviceName, includeParam),
    enabled: Boolean(deviceName),
    refetchInterval: (query: {
      state: { data?: SyncedResource<ArpTableRead> };
    }) => (query.state.data?.sync_in_progress ? SYNC_POLL_INTERVAL_MS : false),
  });

  const macQuery = useQuery({
    queryKey: ['mac-table', deviceName, includeParam ?? ''],
    queryFn: () => getMacTable(deviceName, includeParam),
    enabled: Boolean(deviceName),
    refetchInterval: (query: {
      state: { data?: SyncedResource<MacTableRead> };
    }) => (query.state.data?.sync_in_progress ? SYNC_POLL_INTERVAL_MS : false),
  });

  const inProgress = Boolean(
    arpQuery.data?.sync_in_progress || macQuery.data?.sync_in_progress,
  );
  const syncedAt =
    arpQuery.data?.synced_at ?? macQuery.data?.synced_at ?? null;
  const syncError =
    arpQuery.data?.sync_error ?? macQuery.data?.sync_error ?? null;

  const arpEntries = arpQuery.data?.data.entries ?? null;
  const macEntries = macQuery.data?.data.entries ?? null;

  const [refreshing, setRefreshing] = useState(false);
  async function handleRefresh() {
    setRefreshing(true);
    try {
      await refreshDeviceArpMac(deviceName);
    } finally {
      queryClient.invalidateQueries({ queryKey: ['arp-table', deviceName] });
      queryClient.invalidateQueries({ queryKey: ['mac-table', deviceName] });
      setRefreshing(false);
    }
  }

  const [macSearching, setMacSearching] = useState(false);
  const [macSearchResult, setMacSearchResult] = useState<ArpMacEntry[] | null>(null);
  const [macSearchError, setMacSearchError] = useState<string | null>(null);

  async function handleMacLiveSearch() {
    if (!includeValid || rawInclude === '') return;
    setMacSearching(true);
    setMacSearchResult(null);
    setMacSearchError(null);
    try {
      const { job_id } = await searchMacTable(deviceName, rawInclude);
      for (let attempt = 0; attempt < 20; attempt++) {
        await new Promise((r) => setTimeout(r, 1500));
        const job = await getJob(job_id);
        if (job.status === 'completed') {
          const entries = (job.result as { entries?: ArpMacEntry[] } | null)?.entries ?? [];
          setMacSearchResult(entries);
          return;
        }
        if (job.status === 'failed' || job.status === 'cancelled') {
          setMacSearchError(job.error ?? 'Search failed.');
          return;
        }
      }
      setMacSearchError('Search timed out — try again.');
    } catch (err) {
      setMacSearchError(err instanceof Error ? err.message : 'Search failed.');
    } finally {
      setMacSearching(false);
    }
  }

  const loading = arpQuery.isLoading || macQuery.isLoading;
  const neverSynced =
    !loading &&
    !inProgress &&
    !syncError &&
    syncedAt === null &&
    arpEntries === null &&
    macEntries === null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex-1 max-w-md">
          <input
            type="text"
            value={rawInclude}
            onChange={(e) => setRawInclude(e.target.value)}
            placeholder="Filter (case-insensitive substring across all fields)"
            aria-invalid={!includeValid}
            className={`w-full rounded-md bg-panel-elev border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-info ${
              includeValid ? 'border-panel-border' : 'border-danger'
            }`}
          />
          {!includeValid && (
            <p className="text-xs text-danger mt-1">
              Only letters, digits and <span className="font-mono">:./_-</span> allowed (max 64 chars).
            </p>
          )}
        </div>
        <RefreshButton
          onClick={handleRefresh}
          loading={refreshing || inProgress}
          syncedAt={syncedAt}
          syncError={syncError}
        />
      </div>

      {syncError && (arpEntries === null || arpEntries.length === 0)
        && (macEntries === null || macEntries.length === 0) && (
        <div className="rounded-md border border-danger/60 bg-danger/10 text-danger px-3 py-2 text-sm">
          Last sync failed: {syncError}
        </div>
      )}

      {neverSynced && (
        <div className="rounded-md border border-panel-border bg-panel-elev/40 text-muted px-3 py-2 text-sm italic">
          ARP / MAC tables aren&apos;t synced automatically on device
          registration — click Refresh to populate them for the first time.
          Bigger devices can take a while.
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Panel
          title="ARP table"
          actions={
            <span className="text-xs text-muted tabular-nums">
              {arpEntries?.length ?? 0} row
              {(arpEntries?.length ?? 0) === 1 ? '' : 's'}
            </span>
          }
        >
          <EntriesTable
            entries={arpEntries}
            columns={ARP_COLUMNS}
            loading={loading}
          />
        </Panel>
        <Panel
          title="MAC table"
          actions={
            <span className="text-xs text-muted tabular-nums">
              {(macSearchResult ?? macEntries)?.length ?? 0} row
              {((macSearchResult ?? macEntries)?.length ?? 0) === 1 ? '' : 's'}
            </span>
          }
        >
          {!loading && syncError && (macEntries === null || macEntries.length === 0) ? (
            <div className="flex flex-col gap-2">
              <p className="text-sm text-muted">
                Couldn&apos;t bring the full MAC table — large tables can drop
                the SSH read mid-stream. Search for a specific value on the
                device instead:
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleMacLiveSearch}
                  disabled={!includeValid || rawInclude === '' || macSearching}
                  className="rounded-md bg-info px-3 py-1.5 text-sm text-white disabled:opacity-50"
                >
                  {macSearching ? 'Searching…' : 'Search on device'}
                </button>
                <span className="text-xs text-muted">
                  Uses the filter box above — type a MAC/VLAN/interface value, then click Search.
                </span>
              </div>
              {macSearchError && (
                <p className="text-sm text-danger">{macSearchError}</p>
              )}
              {macSearchResult !== null && (
                <EntriesTable
                  entries={macSearchResult}
                  columns={MAC_COLUMNS}
                  loading={false}
                />
              )}
            </div>
          ) : (
            <EntriesTable
              entries={macEntries}
              columns={MAC_COLUMNS}
              loading={loading}
            />
          )}
        </Panel>
      </div>
    </div>
  );
}

function EntriesTable({
  entries,
  columns,
  loading,
}: {
  entries: ArpMacEntry[] | null;
  columns: readonly string[];
  loading: boolean;
}) {
  const usedColumns = useMemo(() => {
    if (!entries || entries.length === 0) return [...columns];
    return columns.filter((c) => entries.some((e) => e[c] != null));
  }, [entries, columns]);

  if (loading) {
    return <p className="text-sm italic text-muted">Loading…</p>;
  }
  if (entries === null) {
    return (
      <p className="text-sm italic text-muted">
        No data cached yet.
      </p>
    );
  }
  if (entries.length === 0) {
    return (
      <p className="text-sm italic text-muted">
        No rows match the current filter.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-xs uppercase tracking-wider text-muted">
          <tr>
            {usedColumns.map((c) => (
              <th key={c} className="text-left font-medium py-1 pr-3">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="font-mono">
          {entries.map((row, i) => (
            <tr key={i} className="border-t border-panel-border">
              {usedColumns.map((c) => {
                const v = row[c];
                return (
                  <td key={c} className="py-1 pr-3 text-text">
                    {v === null || v === undefined ? '—' : String(v)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
