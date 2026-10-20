'use client';

import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { batchUpdateSvi, parseFieldErrors } from '@/services/api';
import { useJobNotifications } from '@/context/JobNotificationContext';
import type { SVIBatchRequest } from '@/types/svi';
import type { SviRow } from './scopeSvis';
import { ManagementNotice } from './ManagementNotice';
import { Modal } from './Modal';
import {
  FieldRow,
  FieldError,
  ModalPrimary,
  ModalSecondary,
  extractMessage,
} from './VlanCreateModal';
import { invalidateSviQueries } from './SVICreateModal';

type Tab = 'general' | 'ipv4' | 'ipv6' | 'acl' | 'dhcp';

const FIELD_TO_TAB: Record<string, Tab> = {
  description: 'general',
  admin_up: 'general',
  ipv4_address: 'ipv4',
  ipv4_secondary_add: 'ipv4',
  ipv4_secondary_remove: 'ipv4',
  ipv6_address: 'ipv6',
  acl_in: 'acl',
  acl_out: 'acl',
  dhcp_relay_add: 'dhcp',
  dhcp_relay_remove: 'dhcp',
};

interface Props {
  open: boolean;
  onClose: () => void;
  row: SviRow | null;
}

export function SVIEditModal({ open, onClose, row }: Props) {
  const queryClient = useQueryClient();
  const { trackGroupJob } = useJobNotifications();

  const [tab, setTab] = useState<Tab>('general');

  const [adminUp, setAdminUp] = useState<boolean | null>(null);
  const [description, setDescription] = useState('');

  const [ipv4Primary, setIpv4Primary] = useState('');
  const [ipv4SecondaryList, setIpv4SecondaryList] = useState<string[]>([]);
  const [ipv4SecondaryDraft, setIpv4SecondaryDraft] = useState('');
  const [ipv4SecondaryAdding, setIpv4SecondaryAdding] = useState(false);

  const [ipv6, setIpv6] = useState('');

  const [aclIn, setAclIn] = useState('');
  const [aclOut, setAclOut] = useState('');

  const [dhcpServers, setDhcpServers] = useState<string[]>([]);
  const [dhcpDraft, setDhcpDraft] = useState('');
  const [dhcpAdding, setDhcpAdding] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string> | null>(null);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!row) return;
    setTab('general');
    setAdminUp(row.adminUp);
    setDescription(row.description ?? '');
    setIpv4Primary(row.ipv4 ?? '');
    setIpv4SecondaryList(row.ipv4SecondaryAddresses.slice());
    setIpv4SecondaryDraft('');
    setIpv4SecondaryAdding(false);
    setIpv6(row.ipv6 ?? '');
    setAclIn(row.aclIn ?? '');
    setAclOut(row.aclOut ?? '');
    setDhcpServers(row.dhcpRelayServers.slice());
    setDhcpDraft('');
    setDhcpAdding(false);
    setError(null);
    setFieldErrors(null);
  }, [row, open]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const initial = row;

  const dhcpDelta = useMemo(() => {
    if (!initial) return { adds: [] as string[], removes: [] as string[] };
    const originalSet = new Set(initial.dhcpRelayServers);
    const currentSet = new Set(dhcpServers);
    return {
      adds: dhcpServers.filter((s) => !originalSet.has(s)),
      removes: initial.dhcpRelayServers.filter((s) => !currentSet.has(s)),
    };
  }, [initial, dhcpServers]);

  const dhcpTotalDelta = dhcpDelta.adds.length + dhcpDelta.removes.length;

  const ipv4SecondaryDelta = useMemo(() => {
    if (!initial) return { adds: [] as string[], removes: [] as string[] };
    const originalSet = new Set(initial.ipv4SecondaryAddresses);
    const currentSet = new Set(ipv4SecondaryList);
    return {
      adds: ipv4SecondaryList.filter((s) => !originalSet.has(s)),
      removes: initial.ipv4SecondaryAddresses.filter((s) => !currentSet.has(s)),
    };
  }, [initial, ipv4SecondaryList]);

  const ipv4SecondaryTotalDelta = ipv4SecondaryDelta.adds.length + ipv4SecondaryDelta.removes.length;

  const pending = useMemo<{ body: SVIBatchRequest; labels: string[] }>(() => {
    if (!initial) return { body: {}, labels: [] };
    const body: SVIBatchRequest = {};
    const labels: string[] = [];

    const descNext = description.trim();
    if (descNext !== (initial.description ?? '')) {
      body.description = descNext;
      labels.push(descNext === '' ? 'clear description' : 'set description');
    }

    if (adminUp !== null && adminUp !== initial.adminUp) {
      body.admin_up = adminUp;
      labels.push(`admin ${adminUp ? 'up' : 'down'}`);
    }

    const p4Next = ipv4Primary.trim();
    if (p4Next !== (initial.ipv4 ?? '')) {
      body.ipv4_address = p4Next;
      labels.push(p4Next === '' ? 'clear IPv4 primary' : 'set IPv4 primary');
    }

    const v6Next = ipv6.trim();
    if (v6Next !== (initial.ipv6 ?? '')) {
      body.ipv6_address = v6Next;
      labels.push(v6Next === '' ? 'clear IPv6' : 'set IPv6');
    }

    const aInNext = aclIn.trim();
    if (aInNext !== (initial.aclIn ?? '')) {
      body.acl_in = aInNext;
      labels.push(aInNext === '' ? 'clear ACL in' : 'set ACL in');
    }

    const aOutNext = aclOut.trim();
    if (aOutNext !== (initial.aclOut ?? '')) {
      body.acl_out = aOutNext;
      labels.push(aOutNext === '' ? 'clear ACL out' : 'set ACL out');
    }

    if (dhcpDelta.removes.length > 0) {
      body.dhcp_relay_remove = dhcpDelta.removes[0];
      labels.push(`remove DHCP relay ${dhcpDelta.removes[0]}`);
    } else if (dhcpDelta.adds.length > 0) {
      body.dhcp_relay_add = dhcpDelta.adds[0];
      labels.push(`add DHCP relay ${dhcpDelta.adds[0]}`);
    }

    if (ipv4SecondaryDelta.removes.length > 0) {
      body.ipv4_secondary_remove = ipv4SecondaryDelta.removes[0];
      labels.push(`remove IPv4 secondary ${ipv4SecondaryDelta.removes[0]}`);
    } else if (ipv4SecondaryDelta.adds.length > 0) {
      body.ipv4_secondary_add = ipv4SecondaryDelta.adds[0];
      labels.push(`add IPv4 secondary ${ipv4SecondaryDelta.adds[0]}`);
    }

    return { body, labels };
  }, [
    initial,
    description,
    adminUp,
    ipv4Primary,
    ipv6,
    aclIn,
    aclOut,
    dhcpDelta,
    ipv4SecondaryDelta,
  ]);

  const totalChanges = pending.labels.length;

  const dirtyByTab = useMemo(() => {
    if (!initial) {
      return { general: false, ipv4: false, ipv6: false, acl: false, dhcp: false };
    }
    return {
      general:
        description.trim() !== (initial.description ?? '') ||
        (adminUp !== null && adminUp !== initial.adminUp),
      ipv4:
        ipv4Primary.trim() !== (initial.ipv4 ?? '') ||
        ipv4SecondaryDelta.adds.length > 0 ||
        ipv4SecondaryDelta.removes.length > 0,
      ipv6: ipv6.trim() !== (initial.ipv6 ?? ''),
      acl:
        aclIn.trim() !== (initial.aclIn ?? '') ||
        aclOut.trim() !== (initial.aclOut ?? ''),
      dhcp: dhcpDelta.adds.length > 0 || dhcpDelta.removes.length > 0,
    };
  }, [
    initial,
    description,
    adminUp,
    ipv4Primary,
    ipv6,
    aclIn,
    aclOut,
    dhcpDelta,
    ipv4SecondaryDelta,
  ]);

  const errorTabs = useMemo(() => {
    const tabs = new Set<Tab>();
    if (!fieldErrors) return tabs;
    for (const field of Object.keys(fieldErrors)) {
      const t = FIELD_TO_TAB[field];
      if (t) tabs.add(t);
    }
    return tabs;
  }, [fieldErrors]);

  const mutation = useMutation({
    mutationFn: async () => {
      if (!initial || Object.keys(pending.body).length === 0) return;
      return batchUpdateSvi(initial.device, initial.vlanId, pending.body);
    },
    onSuccess: (result) => {
      if (result && initial) {
        trackGroupJob(
          result.group_job_id,
          `Update SVI ${initial.vlanId} on ${initial.device}`,
        );
      }
      onClose();
    },
    onSettled: () => invalidateSviQueries(queryClient),
    onError: (err: unknown) => {
      const fields = parseFieldErrors(err);
      setFieldErrors(fields);
      setError(fields ? null : extractMessage(err, 'Save failed.'));
      if (fields) {
        const firstField = Object.keys(fields)[0];
        const targetTab = FIELD_TO_TAB[firstField];
        if (targetTab) setTab(targetTab);
      }
    },
  });

  function queueAddDhcpServer() {
    if (dhcpTotalDelta >= 1) return;
    const v = dhcpDraft.trim();
    if (!v) return;
    if (dhcpServers.includes(v)) {
      setDhcpDraft('');
      setDhcpAdding(false);
      return;
    }
    setDhcpServers([...dhcpServers, v]);
    setDhcpDraft('');
    setDhcpAdding(false);
  }

  function queueRemoveDhcpServer(s: string) {
    const isNewlyAdded = !(initial?.dhcpRelayServers ?? []).includes(s);
    if (!isNewlyAdded && dhcpTotalDelta >= 1) return;
    setDhcpServers(dhcpServers.filter((x) => x !== s));
  }

  function queueAddIpv4Secondary() {
    if (ipv4SecondaryTotalDelta >= 1) return;
    const v = ipv4SecondaryDraft.trim();
    if (!v) return;
    if (ipv4SecondaryList.includes(v)) {
      setIpv4SecondaryDraft('');
      setIpv4SecondaryAdding(false);
      return;
    }
    setIpv4SecondaryList([...ipv4SecondaryList, v]);
    setIpv4SecondaryDraft('');
    setIpv4SecondaryAdding(false);
  }

  function queueRemoveIpv4Secondary(s: string) {
    const isNewlyAdded = !(initial?.ipv4SecondaryAddresses ?? []).includes(s);
    if (!isNewlyAdded && ipv4SecondaryTotalDelta >= 1) return;
    setIpv4SecondaryList(ipv4SecondaryList.filter((x) => x !== s));
  }

  const canSubmit = totalChanges > 0 && !mutation.isPending;

  if (!row) return null;

  return (
    <Modal
      open={open}
      onClose={() => (mutation.isPending ? undefined : onClose())}
      title={`Edit SVI — VLAN ${row.vlanId} on ${row.device}`}
      widthClass="w-full max-w-2xl"
      footer={
        <>
          <span className="text-xs text-muted mr-auto">
            {totalChanges === 0
              ? 'No changes'
              : `${totalChanges} pending change${totalChanges === 1 ? '' : 's'}`}
          </span>
          <ModalSecondary onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </ModalSecondary>
          <ModalPrimary onClick={() => mutation.mutate()} disabled={!canSubmit}>
            {mutation.isPending ? 'Saving…' : 'Save'}
          </ModalPrimary>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {row.isManagement && (
          <ManagementNotice>
            This is the management SVI of {row.device}: the app reaches the device
            through it. Shutting it down or changing its IP or ACL can cut management
            access, and a rollback cannot recover a path that is gone.
          </ManagementNotice>
        )}
        <TabBar
          tab={tab}
          onChange={setTab}
          dirty={dirtyByTab}
          errorTabs={errorTabs}
          disabled={mutation.isPending}
        />

        {tab === 'general' && (
          <GeneralTab
            adminUp={adminUp}
            onAdminUpChange={setAdminUp}
            initialAdminUp={initial?.adminUp ?? null}
            description={description}
            onDescriptionChange={setDescription}
            descriptionError={fieldErrors?.description}
          />
        )}
        {tab === 'ipv4' && (
          <Ipv4Tab
            primary={ipv4Primary}
            onPrimaryChange={setIpv4Primary}
            secondaryList={ipv4SecondaryList}
            originalSecondaryList={initial?.ipv4SecondaryAddresses ?? []}
            secondaryAddDisabled={ipv4SecondaryTotalDelta >= 1}
            secondaryDraft={ipv4SecondaryDraft}
            onSecondaryDraftChange={setIpv4SecondaryDraft}
            secondaryAdding={ipv4SecondaryAdding}
            onSecondaryAddingChange={setIpv4SecondaryAdding}
            onSecondaryAdd={queueAddIpv4Secondary}
            onSecondaryRemove={queueRemoveIpv4Secondary}
            primaryError={fieldErrors?.ipv4_address}
            secondaryError={fieldErrors?.ipv4_secondary_add ?? fieldErrors?.ipv4_secondary_remove}
          />
        )}
        {tab === 'ipv6' && (
          <Ipv6Tab value={ipv6} onChange={setIpv6} error={fieldErrors?.ipv6_address} />
        )}
        {tab === 'acl' && (
          <AclTab
            aclIn={aclIn}
            onAclInChange={setAclIn}
            aclOut={aclOut}
            onAclOutChange={setAclOut}
            aclInError={fieldErrors?.acl_in}
            aclOutError={fieldErrors?.acl_out}
          />
        )}
        {tab === 'dhcp' && (
          <EditableAddressListTab
            title="DHCP relay servers"
            items={dhcpServers}
            originalItems={initial?.dhcpRelayServers ?? []}
            addDisabled={dhcpTotalDelta >= 1}
            draft={dhcpDraft}
            onDraftChange={setDhcpDraft}
            adding={dhcpAdding}
            onAddingChange={setDhcpAdding}
            onAdd={queueAddDhcpServer}
            onRemove={queueRemoveDhcpServer}
            placeholder="e.g. 10.0.0.53"
            removeAriaLabel={(s) => `Remove relay ${s}`}
            capWarningText="Only 1 DHCP relay change can be queued per Save — undo it or Save first before queuing another."
            footerNote="Queued locally — applied together when you click Save, same as the other tabs (1 DHCP relay change per Save)."
          />
        )}

        {error && (
          <p className="text-sm text-danger border border-danger/40 bg-danger/10 rounded px-3 py-2 whitespace-pre-wrap">
            {error}
          </p>
        )}
      </div>
    </Modal>
  );
}

function TabBar({
  tab,
  onChange,
  dirty,
  errorTabs,
  disabled,
}: {
  tab: Tab;
  onChange: (t: Tab) => void;
  dirty: Record<Tab, boolean>;
  errorTabs: Set<Tab>;
  disabled?: boolean;
}) {
  const items: Array<{ key: Tab; label: string }> = [
    { key: 'general', label: 'General' },
    { key: 'ipv4', label: 'IPv4' },
    { key: 'ipv6', label: 'IPv6' },
    { key: 'acl', label: 'ACL' },
    { key: 'dhcp', label: 'DHCP Relay' },
  ];
  return (
    <div className="flex gap-1 border-b border-panel-border">
      {items.map((it) => {
        const active = tab === it.key;
        return (
          <button
            key={it.key}
            type="button"
            disabled={disabled}
            onClick={() => onChange(it.key)}
            className={`relative px-3 py-1.5 text-xs font-semibold uppercase tracking-wider transition-colors -mb-px border-b-2 ${
              active
                ? 'text-info border-info'
                : 'text-muted border-transparent hover:text-text'
            }`}
          >
            {it.label}
            {errorTabs.has(it.key) ? (
              <span
                className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-danger align-middle"
                title="This tab has a field with an error"
              />
            ) : dirty[it.key] && (
              <span
                className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-warning align-middle"
                title="Unsaved changes"
              />
            )}
          </button>
        );
      })}
    </div>
  );
}

function GeneralTab({
  adminUp,
  onAdminUpChange,
  initialAdminUp,
  description,
  onDescriptionChange,
  descriptionError,
}: {
  adminUp: boolean | null;
  onAdminUpChange: (v: boolean) => void;
  initialAdminUp: boolean | null;
  description: string;
  onDescriptionChange: (v: string) => void;
  descriptionError?: string;
}) {
  return (
    <div className="flex flex-col gap-4">
      <FieldRow label="Description">
        <input
          type="text"
          value={description}
          onChange={(e) => onDescriptionChange(e.target.value)}
          placeholder="Leave empty to clear"
          className="w-full rounded-md bg-panel-elev border border-panel-border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-info"
        />
        <FieldError message={descriptionError} />
        <p className="text-xs text-muted mt-1">
          Clearing the field and saving will DELETE the description on the device.
        </p>
      </FieldRow>

      <FieldRow label="Admin state">
        <div className="flex items-center gap-2">
          <SegButton
            active={adminUp === true}
            onClick={() => onAdminUpChange(true)}
            tone="ok"
          >
            Up
          </SegButton>
          <SegButton
            active={adminUp === false}
            onClick={() => onAdminUpChange(false)}
            tone="danger"
          >
            Down
          </SegButton>
          {initialAdminUp === null && (
            <span className="text-xs text-muted italic">
              current state unknown — pick one to set
            </span>
          )}
        </div>
      </FieldRow>
    </div>
  );
}

function Ipv4Tab({
  primary,
  onPrimaryChange,
  secondaryList,
  originalSecondaryList,
  secondaryAddDisabled,
  secondaryDraft,
  onSecondaryDraftChange,
  secondaryAdding,
  onSecondaryAddingChange,
  onSecondaryAdd,
  onSecondaryRemove,
  primaryError,
  secondaryError,
}: {
  primary: string;
  onPrimaryChange: (v: string) => void;
  secondaryList: string[];
  originalSecondaryList: string[];
  secondaryAddDisabled: boolean;
  secondaryDraft: string;
  onSecondaryDraftChange: (v: string) => void;
  secondaryAdding: boolean;
  onSecondaryAddingChange: (v: boolean) => void;
  onSecondaryAdd: () => void;
  onSecondaryRemove: (s: string) => void;
  primaryError?: string;
  secondaryError?: string;
}) {
  const secondaryBlocked = primary.trim() === '' && secondaryList.length > 0;
  return (
    <div className="flex flex-col gap-4">
      <FieldRow label="Primary address (CIDR)">
        <input
          type="text"
          value={primary}
          onChange={(e) => onPrimaryChange(e.target.value)}
          placeholder="e.g. 10.10.10.11/24 — empty to clear"
          className="w-full rounded-md bg-panel-elev border border-panel-border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-info font-mono"
        />
        <FieldError message={primaryError} />
        {secondaryBlocked && (
          <p className="text-xs text-danger mt-1">
            The device rejects a secondary without a primary. Save will fail
            if you clear the primary while keeping any secondary.
          </p>
        )}
      </FieldRow>

      <EditableAddressListTab
        title="Secondary addresses (CIDR)"
        items={secondaryList}
        originalItems={originalSecondaryList}
        addDisabled={secondaryAddDisabled}
        draft={secondaryDraft}
        onDraftChange={onSecondaryDraftChange}
        adding={secondaryAdding}
        onAddingChange={onSecondaryAddingChange}
        onAdd={onSecondaryAdd}
        onRemove={onSecondaryRemove}
        placeholder="e.g. 10.10.10.12/24 — requires a primary already configured"
        removeAriaLabel={(s) => `Remove secondary address ${s}`}
        capWarningText="Only 1 secondary address change can be queued per Save — undo it or Save first before queuing another."
        footerNote="Queued locally — applied together when you click Save, same as the other tabs (1 secondary address change per Save)."
        error={secondaryError}
      />
    </div>
  );
}

function Ipv6Tab({
  value,
  onChange,
  error,
}: {
  value: string;
  onChange: (v: string) => void;
  error?: string;
}) {
  return (
    <FieldRow label="IPv6 address (CIDR)">
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="e.g. 2001:db8::1/64 — empty to clear"
        className="w-full rounded-md bg-panel-elev border border-panel-border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-info font-mono"
      />
      <FieldError message={error} />
    </FieldRow>
  );
}

function AclTab({
  aclIn,
  onAclInChange,
  aclOut,
  onAclOutChange,
  aclInError,
  aclOutError,
}: {
  aclIn: string;
  onAclInChange: (v: string) => void;
  aclOut: string;
  onAclOutChange: (v: string) => void;
  aclInError?: string;
  aclOutError?: string;
}) {
  return (
    <div className="flex flex-col gap-4">
      <FieldRow label="ACL name — inbound">
        <input
          type="text"
          value={aclIn}
          onChange={(e) => onAclInChange(e.target.value)}
          placeholder="ACL must already exist on the device — empty to unbind"
          className="w-full rounded-md bg-panel-elev border border-panel-border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-info font-mono"
        />
        <FieldError message={aclInError} />
      </FieldRow>
      <FieldRow label="ACL name — outbound">
        <input
          type="text"
          value={aclOut}
          onChange={(e) => onAclOutChange(e.target.value)}
          placeholder="ACL must already exist on the device — empty to unbind"
          className="w-full rounded-md bg-panel-elev border border-panel-border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-info font-mono"
        />
        <FieldError message={aclOutError} />
      </FieldRow>
    </div>
  );
}

function EditableAddressListTab({
  title,
  items,
  originalItems,
  addDisabled,
  draft,
  onDraftChange,
  adding,
  onAddingChange,
  onAdd,
  onRemove,
  placeholder,
  removeAriaLabel,
  capWarningText,
  footerNote,
  error,
}: {
  title: string;
  items: string[];
  originalItems: string[];
  addDisabled: boolean;
  draft: string;
  onDraftChange: (v: string) => void;
  adding: boolean;
  onAddingChange: (v: boolean) => void;
  onAdd: () => void;
  onRemove: (s: string) => void;
  placeholder: string;
  removeAriaLabel: (s: string) => string;
  capWarningText?: string;
  footerNote: string;
  error?: string;
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-md border border-panel-border p-3 flex flex-col gap-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted mb-1">
          {title}
        </p>

        {items.map((s) => {
          const isNewlyAdded = !originalItems.includes(s);
          const removeDisabled = addDisabled && !isNewlyAdded;
          return (
            <div key={s} className="flex items-center gap-2">
              <div className="flex-1 rounded-md bg-panel-elev border border-panel-border px-3 py-2 text-sm text-text font-mono">
                {s}
              </div>
              <button
                type="button"
                onClick={() => onRemove(s)}
                disabled={removeDisabled}
                aria-label={removeAriaLabel(s)}
                className="rounded-md border border-danger/50 text-danger px-3 py-2 text-sm leading-none hover:bg-danger/10 disabled:opacity-40 disabled:cursor-not-allowed transition"
              >
                −
              </button>
            </div>
          );
        })}

        {adding ? (
          <div className="flex items-center gap-2">
            <input
              type="text"
              autoFocus
              value={draft}
              onChange={(e) => onDraftChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  onAdd();
                } else if (e.key === 'Escape') {
                  e.preventDefault();
                  onDraftChange('');
                  onAddingChange(false);
                }
              }}
              placeholder={placeholder}
              className="flex-1 rounded-md bg-panel-elev border border-info px-3 py-2 text-sm text-text font-mono focus:outline-none focus:ring-2 focus:ring-info"
            />
            <button
              type="button"
              onClick={onAdd}
              disabled={draft.trim() === ''}
              className="rounded-md border border-info text-info px-3 py-2 text-xs font-semibold uppercase tracking-wider hover:bg-info/10 disabled:opacity-40 disabled:cursor-not-allowed transition"
            >
              Add
            </button>
            <button
              type="button"
              onClick={() => {
                onDraftChange('');
                onAddingChange(false);
              }}
              className="rounded-md border border-panel-border text-muted px-3 py-2 text-xs font-semibold uppercase tracking-wider hover:text-text transition"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => onAddingChange(true)}
            disabled={addDisabled}
            className="w-full rounded-md border-2 border-dashed border-panel-border px-3 py-2 text-sm text-muted hover:text-text hover:border-muted disabled:opacity-40 disabled:cursor-not-allowed transition"
          >
            + Add
          </button>
        )}
        <FieldError message={error} />
      </div>

      {addDisabled && capWarningText && (
        <p className="text-xs text-warning">{capWarningText}</p>
      )}

      <p className="text-xs text-muted italic">{footerNote}</p>
    </div>
  );
}

function SegButton({
  active,
  onClick,
  tone,
  children,
}: {
  active: boolean;
  onClick: () => void;
  tone: 'ok' | 'danger';
  children: React.ReactNode;
}) {
  const activeCls =
    tone === 'ok'
      ? 'bg-success/20 text-success border-success/50'
      : 'bg-danger/20 text-danger border-danger/50';
  const idleCls =
    'bg-panel-elev text-muted border-panel-border hover:text-text';
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md border px-3 py-1 text-xs font-semibold uppercase tracking-wider transition ${
        active ? activeCls : idleCls
      }`}
    >
      {children}
    </button>
  );
}
