'use client';

import { useMemo } from 'react';
import type { Port } from '@/types/port';
import { classifyPort } from './ChassisGrid';
import { groupPortsByModule } from './portGroups';
import type { PortRef, PortSelection } from './usePortSelection';

interface Props {
  device: string;
  ports: Port[];
  selection: PortSelection;
}

const STATE_CLS = {
  up: 'bg-success/80 border-success',
  down: 'bg-danger/80 border-danger',
  shutdown: 'bg-panel-elev border-panel-border',
  unknown: 'bg-transparent border-panel-border',
} as const;

export function ChassisMulti({ device, ports, selection }: Props) {
  const groups = useMemo(() => groupPortsByModule(ports), [ports]);

  if (groups.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 items-start">
      {groups.map((group) => {
        const cols = Math.max(1, Math.ceil(group.maxIndex / 2));
        return (
          <div
            key={group.moduleLabel}
            className="flex flex-col gap-1.5 items-start"
          >
            <div className="text-xs font-mono text-muted tracking-wide">
              {group.moduleLabel}
            </div>
            <div
              className="grid gap-1.5 p-3 rounded-md bg-panel-elev/40 border border-panel-border"
              style={{
                gridTemplateColumns: `repeat(${cols}, 1.5rem)`,
                gridTemplateRows: 'repeat(2, 1.5rem)',
              }}
              role="grid"
              aria-label={`Chassis view · ${device} · ${group.moduleLabel}`}
            >
              {group.ports.map(({ port, index }) => {
                const state = classifyPort(port);
                const ref: PortRef = { device, interface: port.name };
                const active = selection.isSelected(ref);
                const isLast =
                  selection.lastClicked?.device === device &&
                  selection.lastClicked.interface === port.name;
                const row = index % 2 === 1 ? 1 : 2;
                const col = Math.ceil(index / 2);
                return (
                  <button
                    key={port.name}
                    type="button"
                    aria-label={`${port.name} — ${state}`}
                    aria-pressed={active}
                    title={`${device} · ${port.name} (${state})`}
                    onClick={() => selection.toggle(ref)}
                    style={{
                      gridRow: row,
                      gridColumn: col,
                      ...(active
                        ? {
                            borderColor: 'var(--color-focus)',
                            boxShadow: isLast
                              ? '0 0 0 2px var(--color-info) inset'
                              : undefined,
                          }
                        : {}),
                    }}
                    className={`h-6 w-6 rounded-sm border-2 transition-transform ${
                      STATE_CLS[state]
                    } ${
                      active
                        ? 'ring-2 ring-offset-1 ring-offset-panel'
                        : 'hover:scale-110'
                    }`}
                  />
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
