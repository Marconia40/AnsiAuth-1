'use client';

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { deleteSVI } from '@/services/api';
import { useJobNotifications } from '@/context/JobNotificationContext';
import type { Scope } from './ScopeDashboard';
import type { SviRow } from './scopeSvis';
import { ManagementNotice } from './ManagementNotice';
import { Modal } from './Modal';
import {
  FieldRow,
  ModalDanger,
  ModalSecondary,
  extractMessage,
} from './VlanCreateModal';
import { invalidateSviQueries } from './SVICreateModal';

interface Props {
  open: boolean;
  onClose: () => void;
  scope: Scope;
  rows: SviRow[];
}

export function SVIRemoveModal({ open, onClose, scope: _scope, rows }: Props) {
  const queryClient = useQueryClient();
  const { trackGroupJob } = useJobNotifications();

  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(
    null,
  );

  const mutation = useMutation({
    mutationFn: async () => {
      const targets = rows.filter((r) => picked.has(rowKey(r)));
      setProgress({ done: 0, total: targets.length });
      let done = 0;
      const results = await Promise.allSettled(
        targets.map(async (r) => {
          try {
            return await deleteSVI(r.device, { vlan_id: r.vlanId });
          } finally {
            done += 1;
            setProgress({ done, total: targets.length });
          }
        }),
      );
      const label = `Remove SVI (${targets.length} target(s))`;
      for (const r of results) {
        if (r.status === 'fulfilled') {
          trackGroupJob(r.value.group_job_id, label);
        }
      }

      const failed = results.filter((r) => r.status === 'rejected');
      if (failed.length > 0) {
        const firstErr = (failed[0] as PromiseRejectedResult).reason;
        throw new Error(
          `${failed.length} of ${targets.length} SVI(s) failed to delete: ${extractMessage(firstErr, 'Delete failed.')}`,
        );
      }
    },
    onSuccess: () => {
      invalidateSviQueries(queryClient);
      resetAndClose();
    },
    onError: (err: unknown) =>
      setError(extractMessage(err, 'Remove failed on at least one SVI.')),
  });

  function resetAndClose() {
    setPicked(new Set());
    setError(null);
    setProgress(null);
    onClose();
  }

  function toggle(key: string) {
    const next = new Set(picked);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setPicked(next);
  }

  const canSubmit = picked.size > 0 && !mutation.isPending;
  const pickedManagement = rows.filter((r) => r.isManagement && picked.has(rowKey(r)));

  return (
    <Modal
      open={open}
      onClose={resetAndClose}
      title="Remove virtual interfaces"
      widthClass="w-full max-w-xl"
      footer={
        <>
          <ModalSecondary onClick={resetAndClose} disabled={mutation.isPending}>
            Cancel
          </ModalSecondary>
          <ModalDanger onClick={() => mutation.mutate()} disabled={!canSubmit}>
            {mutation.isPending
              ? progress
                ? `Removing ${progress.done}/${progress.total}…`
                : 'Removing…'
              : `Remove ${picked.size || ''}`.trim()}
          </ModalDanger>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <FieldRow label="Pick SVIs to remove">
          <div className="rounded-md border border-panel-border max-h-72 overflow-y-auto divide-y divide-panel-border">
            {rows.length === 0 ? (
              <p className="p-3 text-sm italic text-muted">
                No virtual interfaces in this scope.
              </p>
            ) : (
              rows.map((row) => {
                const key = rowKey(row);
                return (
                  <label
                    key={key}
                    className="flex items-center gap-3 px-3 py-1.5 text-sm text-text cursor-pointer hover:bg-panel-elev/60"
                  >
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-danger"
                      checked={picked.has(key)}
                      onChange={() => toggle(key)}
                    />
                    <span className="font-semibold tabular-nums w-14">
                      {row.vlanId}
                    </span>
                    <span className="text-muted truncate flex-1">
                      {row.description || (
                        <span className="italic">(no description)</span>
                      )}
                    </span>
                    <span className="text-xs text-muted tabular-nums shrink-0">
                      {row.device}
                    </span>
                  </label>
                );
              })
            )}
          </div>
          {pickedManagement.length > 0 && (
            <ManagementNotice className="mt-2">
              {pickedManagement
                .map((r) => `${r.device} (VLAN ${r.vlanId})`)
                .join(', ')}
              : management SVI. The app reaches {pickedManagement.length === 1 ? 'that device' : 'those devices'} through
              it, removing it can cut management access, and a rollback cannot recover a path that is gone.
            </ManagementNotice>
          )}
          <p className="text-xs text-muted mt-1">
            Each row is a specific (device, VLAN) pair — SVIs are per-device
            L3 interfaces so a single VLAN id can appear multiple times if
            configured on more than one device.
          </p>
        </FieldRow>

        {error && (
          <p className="text-sm text-danger border border-danger/40 bg-danger/10 rounded px-3 py-2">
            {error}
          </p>
        )}
      </div>
    </Modal>
  );
}

function rowKey(row: SviRow): string {
  return `${row.device}:${row.vlanId}`;
}
