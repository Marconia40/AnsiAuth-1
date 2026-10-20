'use client';

import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { createOrUpdateGlobalConfigAcl, parseFieldErrors } from '@/services/api';
import { useJobNotifications } from '@/context/JobNotificationContext';
import { aclManagementRisk } from './managementGuard';
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
import {
  AclRuleEditor,
  draftToRule,
  makeEmptyDraft,
  type RuleDraft,
} from './AclRuleEditor';

interface Props {
  open: boolean;
  onClose: () => void;
  deviceName: string;
  lockedName?: string | null;
}

export function AclCreateOrAddModal({
  open,
  onClose,
  deviceName,
  lockedName,
}: Props) {
  const queryClient = useQueryClient();
  const { trackGroupJob } = useJobNotifications();

  const [name, setName] = useState('');
  const [drafts, setDrafts] = useState<RuleDraft[]>([makeEmptyDraft()]);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string> | null>(null);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!open) return;
    setName(lockedName ?? '');
    setDrafts([makeEmptyDraft()]);
    setError(null);
    setFieldErrors(null);
  }, [open, lockedName]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const normalized = useMemo(() => drafts.map(draftToRule), [drafts]);
  const allComplete = normalized.every((r) => r !== null);
  const rulesReady = normalized.filter((r): r is NonNullable<typeof r> => r !== null);
  const mgmt = useManagementSvi(deviceName);
  const aclRisk = aclManagementRisk(name, mgmt);
  const nameOk = name.trim().length > 0;

  const canSubmit =
    nameOk && rulesReady.length > 0 && allComplete;

  const mutation = useMutation({
    mutationFn: () =>
      createOrUpdateGlobalConfigAcl(deviceName, {
        name: name.trim(),
        rules: rulesReady,
      }),
    onSuccess: (result) => {
      const label = lockedName
        ? `Add rules to ACL ${name.trim()} on ${deviceName}`
        : `Create/update ACL ${name.trim()} on ${deviceName}`;
      trackGroupJob(result.group_job_id, label);
      queryClient.invalidateQueries({
        queryKey: ['global-config', 'synced', deviceName],
      });
      onClose();
    },
    onError: (err: unknown) => {
      const fields = parseFieldErrors(err);
      setFieldErrors(fields);
      setError(fields ? null : extractMessage(err, 'Failed to queue the ACL change.'));
    },
  });

  return (
    <Modal
      open={open}
      onClose={mutation.isPending ? () => undefined : onClose}
      title={
        lockedName
          ? `Add rules — ACL ${lockedName} on ${deviceName}`
          : `Create ACL — ${deviceName}`
      }
      widthClass="w-full max-w-3xl"
      footer={
        <>
          <ModalSecondary onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </ModalSecondary>
          <ModalPrimary
            onClick={() => mutation.mutate()}
            disabled={!canSubmit || mutation.isPending}
          >
            {mutation.isPending
              ? 'Applying…'
              : lockedName
              ? 'Add rules'
              : 'Create'}
          </ModalPrimary>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <FieldRow label="ACL name">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={Boolean(lockedName) || mutation.isPending}
            placeholder="e.g. ACL_MGMT"
            className="w-full rounded-md bg-panel-elev border border-panel-border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-info disabled:opacity-60"
          />
          <FieldError message={fieldErrors?.name} />
        </FieldRow>

        {aclRisk && (
          <ManagementNotice>
            ACL {name.trim()} is {aclRisk} of {deviceName}: new rules can deny the management
            traffic and cut access, and a rollback cannot recover a path that is gone.
          </ManagementNotice>
        )}

        {!lockedName && (
          <p className="text-xs text-muted">
            Only extended (Cisco) / advanced (Huawei) ACLs can be created
            here. Standard / basic ACLs must already exist on the device.
          </p>
        )}

        <AclRuleEditor
          value={drafts}
          onChange={setDrafts}
          disabled={mutation.isPending}
          fieldErrors={fieldErrors}
        />

        {rulesReady.length === 0 && (
          <p className="text-xs text-muted">
            Add at least one rule with all fields filled to enable Apply.
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
