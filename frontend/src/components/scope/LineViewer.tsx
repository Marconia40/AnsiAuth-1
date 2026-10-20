'use client';

import { useMemo } from 'react';

interface Props {
  lines: string[] | null;
  filter: string;
  wrap: boolean;
  showLineNumbers?: boolean;
  neverSyncedLabel: string;
  emptyLabel: string;
  maxHeightClass?: string;
}

export function LineViewer({
  lines,
  filter,
  wrap,
  showLineNumbers,
  neverSyncedLabel,
  emptyLabel,
  maxHeightClass = 'max-h-[60vh]',
}: Props) {
  const filtered = useMemo(() => {
    if (lines === null) return null;
    const q = filter.trim().toLowerCase();
    if (q === '') return lines.map((line, i) => ({ line, index: i }));
    return lines
      .map((line, i) => ({ line, index: i }))
      .filter(({ line }) => line.toLowerCase().includes(q));
  }, [lines, filter]);

  if (lines === null) {
    return (
      <div className="rounded-md border border-panel-border bg-panel-elev/40 text-muted px-3 py-2 text-sm italic">
        {neverSyncedLabel}
      </div>
    );
  }
  if (lines.length === 0) {
    return (
      <p className="text-sm italic text-muted">{emptyLabel}</p>
    );
  }
  if (filtered !== null && filtered.length === 0) {
    return (
      <p className="text-sm italic text-muted">No lines match the filter.</p>
    );
  }
  return (
    <div
      className={`${maxHeightClass} overflow-auto rounded-md bg-panel-elev/60 border border-panel-border`}
    >
      <pre
        className={`text-xs font-mono leading-relaxed py-2 pr-3 ${
          wrap ? 'whitespace-pre-wrap break-all' : 'whitespace-pre'
        }`}
      >
        {(filtered ?? []).map(({ line, index }) => (
          <div key={index} className="flex">
            {showLineNumbers && (
              <span
                aria-hidden
                className="select-none text-muted/60 tabular-nums w-12 pr-2 text-right shrink-0"
              >
                {index + 1}
              </span>
            )}
            <span className="text-text flex-1 pl-2">{line || ' '}</span>
          </div>
        ))}
      </pre>
    </div>
  );
}
