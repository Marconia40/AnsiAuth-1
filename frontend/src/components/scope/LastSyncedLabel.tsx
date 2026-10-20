'use client';

import { formatSyncRelative } from './formatSyncRelative';

export interface LastSyncedLabelProps {
  syncedAt?: string | null;
  syncError?: string | null;
  progressLabel?: string | null;
}

export function LastSyncedLabel({
  syncedAt,
  syncError,
  progressLabel,
}: LastSyncedLabelProps) {
  if (progressLabel) {
    return <span className="text-xs text-muted tabular-nums">{progressLabel}</span>;
  }
  if (syncError) {
    return <span className="text-xs text-danger">{syncError}</span>;
  }
  if (syncedAt) {
    return (
      <span className="text-xs text-muted">
        Last synced {formatSyncRelative(syncedAt)}
      </span>
    );
  }
  return null;
}
