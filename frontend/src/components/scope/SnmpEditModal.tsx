'use client';

import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { setGlobalConfigSnmp, parseFieldErrors } from '@/services/api';
import { useJobNotifications } from '@/context/JobNotificationContext';
import type {
  GlobalConfigSnmpInfo,
  SnmpUpdateRequest,
} from '@/types/global-config';
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
  currentSnmp: GlobalConfigSnmpInfo | null;
}

export function SnmpEditModal({
  open,
  onClose,
  deviceName,
  currentSnmp,
}: Props) {
  const queryClient = useQueryClient();
  const { trackGroupJob } = useJobNotifications();

  const [version, setVersion] = useState('');
  const [community, setCommunity] = useState('');
  const [trapSource, setTrapSource] = useState('');
  const [trapHost, setTrapHost] = useState('');
  const [trapVersion, setTrapVersion] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string> | null>(null);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!open) return;
    setVersion(currentSnmp?.version ?? '');
    setCommunity(currentSnmp?.community ?? '');
    setTrapSource('');
    setTrapHost('');
    setTrapVersion('');
    setError(null);
    setFieldErrors(null);
  }, [open, currentSnmp]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const trimmedVersion = version.trim();
  const trimmedCommunity = community.trim();
  const trimmedTrapSource = trapSource.trim();
  const trimmedTrapHost = trapHost.trim();
  const trimmedTrapVersion = trapVersion.trim();

  const trapPairMismatch =
    (trimmedTrapHost === '') !== (trimmedTrapVersion === '');
  const trapPairComplete =
    trimmedTrapHost !== '' && trimmedTrapVersion !== '';

  const anySet =
    trimmedVersion !== '' ||
    trimmedCommunity !== '' ||
    trimmedTrapSource !== '' ||
    trapPairComplete;

  const body: SnmpUpdateRequest = useMemo(() => {
    const out: SnmpUpdateRequest = {};
    if (trimmedVersion !== '') out.version = trimmedVersion;
    if (trimmedCommunity !== '') out.community = trimmedCommunity;
    if (trimmedTrapSource !== '') out.trap_source = trimmedTrapSource;
    if (trapPairComplete) {
      out.trap_host = trimmedTrapHost;
      out.trap_version = trimmedTrapVersion;
    }
    return out;
  }, [
    trimmedVersion,
    trimmedCommunity,
    trimmedTrapSource,
    trapPairComplete,
    trimmedTrapHost,
    trimmedTrapVersion,
  ]);

  const mutation = useMutation({
    mutationFn: () => setGlobalConfigSnmp(deviceName, body),
    onSuccess: (result) => {
      trackGroupJob(result.group_job_id, `Update SNMP on ${deviceName}`);
      queryClient.invalidateQueries({
        queryKey: ['global-config', 'synced', deviceName],
      });
      onClose();
    },
    onError: (err: unknown) => {
      const fields = parseFieldErrors(err);
      setFieldErrors(fields);
      setError(fields ? null : extractMessage(err, 'Failed to queue the SNMP change.'));
    },
  });

  const canSubmit =
    anySet && !trapPairMismatch && !mutation.isPending;

  return (
    <Modal
      open={open}
      onClose={mutation.isPending ? () => undefined : onClose}
      title={`Edit SNMP — ${deviceName}`}
      footer={
        <>
          <ModalSecondary onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </ModalSecondary>
          <ModalPrimary
            onClick={() => mutation.mutate()}
            disabled={!canSubmit}
          >
            {mutation.isPending ? 'Applying…' : 'Apply'}
          </ModalPrimary>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <p className="text-xs text-muted">
          Community is applied as read-only. Leave a field blank to leave it
          untouched — at least one knob must be filled.
        </p>

        <FieldRow label="Version">
          <select
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            className="w-full rounded-md bg-panel-elev border border-panel-border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-info"
          >
            <option value="">Leave untouched</option>
            <option value="v1">v1</option>
            <option value="v2c">v2c</option>
            <option value="v3">v3</option>
          </select>
          <p className="text-xs text-muted mt-1">
            Only takes effect on Huawei (VRP) — Cisco has no separate version
            command, this is ignored there.
          </p>
          <FieldError message={fieldErrors?.version} />
        </FieldRow>

        <FieldRow label="Community">
          <input
            type="text"
            value={community}
            onChange={(e) => setCommunity(e.target.value)}
            placeholder="e.g. public"
            className="w-full rounded-md bg-panel-elev border border-panel-border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-info"
          />
          <FieldError message={fieldErrors?.community} />
        </FieldRow>

        <FieldRow label="Trap source interface">
          <input
            type="text"
            value={trapSource}
            onChange={(e) => setTrapSource(e.target.value)}
            placeholder="e.g. Loopback0"
            className="w-full rounded-md bg-panel-elev border border-panel-border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-info"
          />
          <FieldError message={fieldErrors?.trap_source} />
        </FieldRow>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <FieldRow label="Trap host">
            <input
              type="text"
              value={trapHost}
              onChange={(e) => setTrapHost(e.target.value)}
              placeholder="e.g. 10.0.0.5"
              className="w-full rounded-md bg-panel-elev border border-panel-border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-info"
            />
            <FieldError message={fieldErrors?.trap_host} />
          </FieldRow>
          <FieldRow label="Trap version">
            <select
              value={trapVersion}
              onChange={(e) => setTrapVersion(e.target.value)}
              className="w-full rounded-md bg-panel-elev border border-panel-border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-info"
            >
              <option value="">—</option>
              <option value="1">1</option>
              <option value="2c">2c</option>
              <option value="3">3</option>
            </select>
            <p className="text-xs text-muted mt-1">
              IOS format (no &apos;v&apos; prefix). Huawei&apos;s trap-host
              always uses v2c regardless of this value.
            </p>
            <FieldError message={fieldErrors?.trap_version} />
          </FieldRow>
        </div>

        {trapPairMismatch && (
          <p className="text-xs text-danger">
            Trap host and trap version must be provided together.
          </p>
        )}
        {!anySet && (
          <p className="text-xs text-muted">
            Fill at least one field to enable Apply.
          </p>
        )}

        {error && (
          <p className="text-sm text-danger border border-danger/40 bg-danger/10 rounded px-3 py-2">
            {error}
          </p>
        )}
      </div>
    </Modal>
  );
}
