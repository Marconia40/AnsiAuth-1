'use client';

export type PortActionId = 'edit' | 'reset';

interface RailItem {
  id: PortActionId;
  label: string;
  tone?: 'default' | 'danger';
}

const RAIL: RailItem[] = [
  { id: 'edit', label: 'Edit' },
  { id: 'reset', label: 'Delete Ports Config', tone: 'danger' },
];

interface Props {
  disabled: boolean;
  onOpen: (id: PortActionId) => void;
}

export function PortActionRail({ disabled, onOpen }: Props) {
  return (
    <div className="flex flex-col gap-2 sticky top-2">
      {RAIL.map((item) => {
        const cls =
          item.tone === 'danger'
            ? 'border-danger/60 text-danger hover:bg-danger/10'
            : 'border-panel-border text-text hover:bg-panel-elev';
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => onOpen(item.id)}
            disabled={disabled}
            className={`rounded-md border ${cls} text-xs font-semibold uppercase tracking-wide px-3 py-2 text-center leading-tight disabled:opacity-40 disabled:cursor-not-allowed transition-colors`}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
