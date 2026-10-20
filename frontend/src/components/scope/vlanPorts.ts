import type { Port } from '@/types/port';

export function vlanPortsForDevice(
  ports: Port[],
  vlanId: number,
): string[] {
  const out: { label: string; sortKey: string }[] = [];
  for (const p of ports) {
    let tagged: boolean | null = null;
    if (p.mode === 'access') {
      if (p.access_vlan === vlanId) tagged = false;
    } else if (p.mode === 'trunk') {
      if (p.access_vlan === vlanId) {
        tagged = false;
      } else if (p.allowed_vlans?.includes(vlanId)) {
        tagged = true;
      }
    } else {
      if (p.access_vlan === vlanId) tagged = false;
    }
    if (tagged === null) continue;
    const fullName = p.name_full ?? p.name;
    out.push({ label: tagged ? fullName : `${fullName}(U)`, sortKey: fullName });
  }
  out.sort((a, b) => a.sortKey.localeCompare(b.sortKey, undefined, { numeric: true }));
  return out.map((o) => o.label);
}
