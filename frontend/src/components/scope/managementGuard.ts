import type { Port } from '@/types/port';
import type { PortRef } from './usePortSelection';
import type { TrunkDiffRow } from './trunkDiff';

export interface ManagementWarning {
  device: string;
  interface: string;
  vlan: number;
  what: string;
}

export interface PortChangeIntent {
  adminDown: boolean;
  mode:
    | null
    | { kind: 'access'; vlan: number | null }
    | { kind: 'trunk'; native: number; diffs: TrunkDiffRow[] };
  trunkDiffs: TrunkDiffRow[];
}

export function carriesManagementVlan(port: Port | undefined, vlan: number): boolean {
  if (!port || port.operational_up === false) return false;
  if (port.mode === 'access') return port.access_vlan === vlan;
  if (port.mode === 'trunk') {
    return port.access_vlan === vlan || port.allowed_vlans === null || port.allowed_vlans.includes(vlan);
  }
  return false;
}

function findPort(portsByDevice: Map<string, Port[]>, ref: PortRef): Port | undefined {
  return portsByDevice.get(ref.device)?.find((p) => p.name === ref.interface);
}

export function portManagementWarnings(
  refs: PortRef[],
  portsByDevice: Map<string, Port[]>,
  managementVlanByDevice: Map<string, number | null>,
  intent: PortChangeIntent,
): ManagementWarning[] {
  const out: ManagementWarning[] = [];
  const trunkRows = new Map(intent.trunkDiffs.map((r) => [`${r.device}/${r.interface}`, r]));
  const modeRows =
    intent.mode?.kind === 'trunk'
      ? new Map(intent.mode.diffs.map((r) => [`${r.device}/${r.interface}`, r]))
      : new Map<string, TrunkDiffRow>();

  for (const ref of refs) {
    const vlan = managementVlanByDevice.get(ref.device);
    if (vlan == null) continue;
    const port = findPort(portsByDevice, ref);
    if (!carriesManagementVlan(port, vlan)) continue;
    const add = (what: string) => out.push({ device: ref.device, interface: ref.interface, vlan, what });
    const key = `${ref.device}/${ref.interface}`;

    if (intent.adminDown) add('shuts down a port that carries it');

    const mode = intent.mode;
    if (mode?.kind === 'access' && mode.vlan !== null && mode.vlan !== vlan) {
      add(`moves the port out of VLAN ${vlan}`);
    }
    if (mode?.kind === 'trunk') {
      const row = modeRows.get(key);
      if (port?.mode === 'access' && mode.native !== vlan) {
        add(`turns the access port into a trunk with native VLAN ${mode.native}`);
      }
      if (row?.kind === 'delta') {
        if (row.removed.includes(vlan)) add(`removes VLAN ${vlan} from the trunk`);
        if (row.pvid && row.pvid.from === vlan) add(`moves the native VLAN away from ${vlan}`);
      }
    }

    const tr = trunkRows.get(key);
    if (tr?.known && tr.removed.includes(vlan)) add(`removes VLAN ${vlan} from the trunk`);
  }
  return out;
}

export function anyPortCarriesManagement(
  refs: PortRef[],
  portsByDevice: Map<string, Port[]>,
  managementVlanByDevice: Map<string, number | null>,
): boolean {
  return refs.some((ref) => {
    const vlan = managementVlanByDevice.get(ref.device);
    return vlan != null && carriesManagementVlan(findPort(portsByDevice, ref), vlan);
  });
}

export interface ManagementSvi {
  vlan: number;
  subnets: string[];
  aclIn: string | null;
  aclOut: string | null;
}

function ipv4ToInt(ip: string): number | null {
  const parts = ip.trim().split('.');
  if (parts.length !== 4) return null;
  let n = 0;
  for (const p of parts) {
    if (!/^\d{1,3}$/.test(p)) return null;
    const v = Number(p);
    if (v > 255) return null;
    n = n * 256 + v;
  }
  return n;
}

export function ipv4InCidr(ip: string, cidr: string): boolean {
  const [base, len] = cidr.trim().split('/');
  const a = ipv4ToInt(ip);
  const b = ipv4ToInt(base ?? '');
  const bits = Number(len);
  if (a === null || b === null || !Number.isInteger(bits) || bits < 0 || bits > 32) return false;
  if (bits === 0) return true;
  const size = 2 ** (32 - bits);
  return Math.floor(a / size) === Math.floor(b / size);
}

export function isDefaultRouteDestination(destination: string | null | undefined): boolean {
  return /^0\.0\.0\.0(\/0|[\s/]0\.0\.0\.0)?$/.test((destination ?? '').trim());
}

export function routeManagementRisk(
  destination: string | null | undefined,
  nextHop: string | null | undefined,
  mgmt: ManagementSvi | null,
): string | null {
  if (mgmt === null) return null;
  if (isDefaultRouteDestination(destination)) return 'default route';
  if (nextHop && mgmt.subnets.some((s) => s.split('/')[0] === nextHop.trim())) return null;
  if (nextHop && mgmt.subnets.some((s) => ipv4InCidr(nextHop, s))) {
    return 'next hop on the management network';
  }
  return null;
}

export function aclManagementRisk(aclName: string, mgmt: ManagementSvi | null): string | null {
  const name = aclName.trim();
  if (mgmt === null || name === '') return null;
  const where = [
    mgmt.aclIn === name ? 'inbound' : null,
    mgmt.aclOut === name ? 'outbound' : null,
  ].filter((w): w is string => w !== null);
  return where.length === 0 ? null : `applied ${where.join(' and ')} on the management SVI`;
}
