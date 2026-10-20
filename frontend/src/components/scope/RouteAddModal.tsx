'use client';

import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { addGlobalConfigRoute, parseFieldErrors } from '@/services/api';
import { useJobNotifications } from '@/context/JobNotificationContext';
import { isDefaultRouteDestination } from './managementGuard';
import { useManagementSvi } from './useManagementSvi';
import { ManagementNotice } from './ManagementNotice';
import { Modal } from './Modal';
import {
  FieldRow,
  FieldError,
  ModalPrimary,
  ModalSecondary,
  extractMessage,
} from './VlanCreateModal';

interface Props {
  open: boolean;
  onClose: () => void;
  deviceName: string;
}

export function RouteAddModal({ open, onClose, deviceName }: Props) {
  const queryClient = useQueryClient();
  const { trackGroupJob } = useJobNotifications();

  const [destination, setDestination] = useState('');
  const [nextHop, setNextHop] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string> | null>(null);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!open) return;
    setDestination('');
    setNextHop('');
    setError(null);
    setFieldErrors(null);
  }, [open]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const mgmt = useManagementSvi(deviceName);
  const dTrim = destination.trim();
  const nhTrim = nextHop.trim();
  const destinationLooksCidr = /\//.test(dTrim);
  const canSubmit = dTrim !== '' && nhTrim !== '';

  const mutation = useMutation({
    mutationFn: () =>
      addGlobalConfigRoute(deviceName, {
        destination: dTrim,
        next_hop: nhTrim,
      }),
    onSuccess: (result) => {
      trackGroupJob(
        result.group_job_id,
        `Add route ${dTrim} → ${nhTrim} on ${deviceName}`,
      );
      queryClient.invalidateQueries({
        queryKey: ['global-config', 'synced', deviceName],
      });
      onClose();
    },
    onError: (err: unknown) => {
      const fields = parseFieldErrors(err);
      setFieldErrors(fields);
      setError(fields ? null : extractMessage(err, 'Failed to queue the route addition.'));
    },
  });

  return (
    <Modal
      open={open}
      onClose={mutation.isPending ? () => undefined : onClose}
      title={`Add static route — ${deviceName}`}
      footer={
        <>
          <ModalSecondary onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </ModalSecondary>
          <ModalPrimary
            onClick={() => mutation.mutate()}
            disabled={!canSubmit || mutation.isPending}
          >
            {mutation.isPending ? 'Applying…' : 'Add'}
          </ModalPrimary>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <FieldRow label="Destination (CIDR)">
          <input
            type="text"
            value={destination}
            onChange={(e) => setDestination(e.target.value)}
            placeholder="e.g. 192.168.99.0/24"
            className="w-full rounded-md bg-panel-elev border border-panel-border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-info"
          />
          {dTrim !== '' && !destinationLooksCidr && (
            <p className="text-xs text-danger mt-1">
              Destination must include a prefix length, e.g. /24.
            </p>
          )}
          <FieldError message={fieldErrors?.destination} />
        </FieldRow>

        <FieldRow label="Next-hop IP">
          <input
            type="text"
            value={nextHop}
            onChange={(e) => setNextHop(e.target.value)}
            placeholder="e.g. 10.0.0.1"
            className="w-full rounded-md bg-panel-elev border border-panel-border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-info"
          />
          <FieldError message={fieldErrors?.next_hop} />
        </FieldRow>

        {mgmt !== null && isDefaultRouteDestination(dTrim) && (
          <ManagementNotice>
            A default route can change the path {deviceName} uses to answer its management
            traffic. If the next hop is wrong, management access can be cut, and a rollback
            cannot recover a path that is gone.
          </ManagementNotice>
        )}

        <p className="text-xs text-muted">
          If a route with the same destination already exists but with a
          different next-hop, the backend will NOT overwrite it — remove
          the old route first, then add the new one.
        </p>

        {error && (
          <p className="text-sm text-danger border border-danger/40 bg-danger/10 rounded px-3 py-2">
            {error}
          </p>
        )}
      </div>
    </Modal>
  );
}
