import type { Port, TrunkVlanMode } from '@/types/port';
import type { PortRef } from './usePortSelection';

export interface TrunkDiffRow {
  device: string;
  interface: string;
  known: boolean;
  added: number[];
  removed: number[];
  wouldEmpty: boolean;
  kind?: 'delta' | 'fromAccess' | 'other';
  pvid?: { from: number | null; to: number } | null;
}

const sortedUnique = (list: number[]): number[] =>
  Array.from(new Set(list)).sort((a, b) => a - b);

export function computeTrunkDiff(
  op: TrunkVlanMode,
  requested: number[],
  current: number[] | null,
): Pick<TrunkDiffRow, 'known' | 'added' | 'removed' | 'wouldEmpty'> {
  if (current === null) {
    return { known: false, added: [], removed: [], wouldEmpty: false };
  }
  const now = new Set(current);
  const asked = new Set(requested);
  let finalList: number[];
  if (op === 'replace') finalList = Array.from(asked);
  else if (op === 'add') finalList = [...current, ...requested];
  else finalList = current.filter((v) => !asked.has(v));
  const final = new Set(finalList);
  return {
    known: true,
    added: sortedUnique(finalList.filter((v) => !now.has(v))),
    removed: sortedUnique(current.filter((v) => !final.has(v))),
    wouldEmpty: final.size === 0,
  };
}

export function buildTrunkDiffs(
  refs: PortRef[],
  portsByDevice: Map<string, Port[]>,
  op: TrunkVlanMode,
  requested: number[],
): TrunkDiffRow[] {
  return refs.map((ref) => {
    const port = portsByDevice.get(ref.device)?.find((p) => p.name === ref.interface);
    const current = port && port.mode === 'trunk' ? port.allowed_vlans : null;
    return { device: ref.device, interface: ref.interface, ...computeTrunkDiff(op, requested, current) };
  });
}

export function formatTrunkDiff(row: Pick<TrunkDiffRow, 'known' | 'added' | 'removed'>): string {
  if (!row.known) return 'current list unknown (not a trunk or not read in the last sync)';
  if (row.added.length === 0 && row.removed.length === 0) return 'no change';
  const parts: string[] = [];
  if (row.added.length > 0) parts.push(row.added.map((v) => `+${v}`).join(', '));
  if (row.removed.length > 0) parts.push(row.removed.map((v) => `−${v}`).join(', '));
  return parts.join(' · ');
}

export function buildModeTrunkDiffs(
  refs: PortRef[],
  portsByDevice: Map<string, Port[]>,
  nativeVlan: number,
  allowed: number[],
): TrunkDiffRow[] {
  return refs.map((ref) => {
    const port = portsByDevice.get(ref.device)?.find((p) => p.name === ref.interface);
    const base = { device: ref.device, interface: ref.interface };
    if (port && port.mode === 'trunk' && port.allowed_vlans !== null) {
      return {
        ...base,
        ...computeTrunkDiff('replace', allowed, port.allowed_vlans),
        kind: 'delta' as const,
        pvid: port.access_vlan !== nativeVlan ? { from: port.access_vlan, to: nativeVlan } : null,
      };
    }
    return {
      ...base,
      known: false,
      added: [],
      removed: [],
      wouldEmpty: false,
      kind: port && port.mode === 'access' ? ('fromAccess' as const) : ('other' as const),
      pvid: null,
    };
  });
}

export function modeTrunkIsRisky(rows: TrunkDiffRow[]): boolean {
  return rows.some(
    (r) => r.kind === 'other' || (r.kind === 'delta' && (r.removed.length > 0 || r.pvid != null)),
  );
}

export function describeTrunkDiff(row: TrunkDiffRow): string {
  if (row.kind === 'fromAccess') return 'mode change: access \u2192 trunk (native VLAN and allowed list applied)';
  if (row.kind === 'other') {
    return 'state unknown (not in the last sync, hybrid, or list unread) \u2014 the full mode block is sent';
  }
  const parts: string[] = [];
  if (row.kind === 'delta') {
    if (row.added.length > 0) parts.push(row.added.map((v) => `+${v}`).join(', '));
    if (row.removed.length > 0) parts.push(row.removed.map((v) => `\u2212${v}`).join(', '));
    if (row.pvid) parts.push(`native VLAN ${row.pvid.from ?? '?'} \u2192 ${row.pvid.to}`);
    return parts.length > 0 ? parts.join(' \u00b7 ') : 'no change';
  }
  return formatTrunkDiff(row);
}
