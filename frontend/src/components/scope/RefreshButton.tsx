'use client';

import { RefreshIcon } from '../Icon';
import { formatSyncRelative } from './formatSyncRelative';

export interface RefreshButtonProps {
  onClick?: () => void;
  loading?: boolean;
  disabled?: boolean;
  syncedAt?: string | null;
  syncError?: string | null;
  progressLabel?: string | null;
}

export function RefreshButton({
  onClick,
  loading,
  disabled,
  syncedAt,
  syncError,
  progressLabel,
}: RefreshButtonProps) {
  return (
    <div className="flex items-center gap-2">
      {progressLabel ? (
        <span className="text-xs text-muted tabular-nums">{progressLabel}</span>
      ) : syncError ? (
        <span className="text-xs text-danger cursor-help" title={syncError}>
          Sync error
        </span>
      ) : syncedAt ? (
        <span className="text-xs text-muted">
          Last synced {formatSyncRelative(syncedAt)}
        </span>
      ) : null}
      <button
        type="button"
        onClick={onClick}
        disabled={disabled || loading}
        className="inline-flex items-center gap-2 rounded-md border border-panel-border bg-panel px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-text hover:bg-panel-elev disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        <RefreshIcon size={14} className={loading ? 'animate-spin' : undefined} />
        {loading ? 'Refreshing…' : 'Refresh'}
      </button>
    </div>
  );
}
