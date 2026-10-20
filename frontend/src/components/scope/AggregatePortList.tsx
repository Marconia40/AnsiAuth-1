'use client';

import type { Port } from '@/types/port';
import { classifyPort, STATE_CLS } from './ChassisGrid';

interface Props {
  ports: Port[];
  isSelected: (portName: string) => boolean;
  onClick: (portName: string) => void;
}

export function AggregatePortList({ ports, isSelected, onClick }: Props) {
  if (ports.length === 0) return null;

  return (
    <div className="flex flex-col gap-1.5 items-start">
      <div className="text-xs font-mono text-muted tracking-wide">
        Aggregates
      </div>
      <div className="flex flex-wrap gap-1.5">
        {ports.map((port) => {
          const state = classifyPort(port);
          const active = isSelected(port.name);
          return (
            <button
              key={port.name}
              type="button"
              aria-label={`${port.name} — ${state}`}
              aria-pressed={active}
              title={`${port.name_full} (${state})`}
              onClick={() => onClick(port.name)}
              style={active ? { borderColor: 'var(--color-focus)' } : undefined}
              className={`flex items-center gap-1.5 rounded-md border-2 px-2 py-1 text-xs font-medium text-white transition-colors ${
                STATE_CLS[state]
              } ${active ? 'ring-2 ring-offset-1 ring-offset-panel' : 'hover:brightness-110'}`}
            >
              {port.name_full}
            </button>
          );
        })}
      </div>
    </div>
  );
}
