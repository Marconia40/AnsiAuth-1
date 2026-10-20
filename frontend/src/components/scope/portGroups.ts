import type { Port } from '@/types/port';

const PHYSICAL_PORT_PATTERN = /^([A-Za-z0-9]*[A-Za-z]\d+(?:\/\d+)*)\/(\d+)$/;

export interface PortGroupEntry {
  port: Port;
  index: number;
}

export interface PortGroup {
  moduleLabel: string;
  ports: PortGroupEntry[];
  maxIndex: number;
}

export function groupPortsByModule(ports: Port[]): PortGroup[] {
  const buckets = new Map<string, PortGroupEntry[]>();
  for (const port of ports) {
    const match = PHYSICAL_PORT_PATTERN.exec(port.name);
    if (!match) continue;
    const moduleLabel = match[1];
    const index = Number.parseInt(match[2], 10);
    let entries = buckets.get(moduleLabel);
    if (!entries) {
      entries = [];
      buckets.set(moduleLabel, entries);
    }
    entries.push({ port, index });
  }

  const groups: PortGroup[] = [];
  for (const [moduleLabel, entries] of buckets) {
    entries.sort((a, b) => a.index - b.index);
    const maxIndex = entries[entries.length - 1]?.index ?? 0;
    groups.push({ moduleLabel, ports: entries, maxIndex });
  }
  groups.sort((a, b) =>
    a.moduleLabel.localeCompare(b.moduleLabel, undefined, {
      numeric: true,
      sensitivity: 'base',
    }),
  );
  return groups;
}

export function splitAggregatePorts(ports: Port[]): { physical: Port[]; aggregates: Port[] } {
  const aggregates = ports.filter((p) => p.kind === 'aggregate');
  const physical = ports.filter((p) => p.kind !== 'aggregate');
  return { physical, aggregates };
}
