'use client';

import { useMemo } from 'react';
import type {
  AclRule,
  AclRuleEndpoint,
  AclRulePort,
} from '@/types/global-config';
import { FieldRow, FieldError } from './VlanCreateModal';

function rowError(fieldErrors: Record<string, string> | null | undefined, idx: number): string | null {
  if (!fieldErrors) return null;
  const prefix = `rules.${idx}.`;
  const hits = Object.entries(fieldErrors).filter(([k]) => k.startsWith(prefix));
  if (hits.length === 0) return null;
  return hits.map(([k, v]) => `${k.slice(prefix.length)}: ${v}`).join('; ');
}

export interface RuleDraft {
  action: 'permit' | 'deny';
  protocol: string;
  srcMode: EndpointMode;
  srcValue: string;
  dstMode: EndpointMode;
  dstValue: string;
  portMode: 'none' | 'eq' | 'range';
  portValue: string;
  portValue2: string;
}

type EndpointMode = 'any' | 'host' | 'network';

export function makeEmptyDraft(): RuleDraft {
  return {
    action: 'permit',
    protocol: 'ip',
    srcMode: 'any',
    srcValue: '',
    dstMode: 'any',
    dstValue: '',
    portMode: 'none',
    portValue: '',
    portValue2: '',
  };
}

export function draftToRule(d: RuleDraft): AclRule | null {
  const source = endpointOrNull(d.srcMode, d.srcValue);
  if (source === null) return null;
  const destination = endpointOrNull(d.dstMode, d.dstValue);
  if (destination === null) return null;

  const rule: AclRule = {
    action: d.action,
    protocol: d.protocol.trim(),
    source,
    destination,
  };
  if (rule.protocol === '') return null;

  if (d.portMode === 'eq') {
    const v = d.portValue.trim();
    if (v === '') return null;
    const port: AclRulePort = { operator: 'eq', value: v };
    rule.port = port;
  } else if (d.portMode === 'range') {
    const v = d.portValue.trim();
    const v2 = d.portValue2.trim();
    if (v === '' || v2 === '') return null;
    const port: AclRulePort = { operator: 'range', value: v, value2: v2 };
    rule.port = port;
  }
  return rule;
}

function endpointOrNull(mode: EndpointMode, value: string): AclRuleEndpoint | null {
  if (mode === 'any') return { any: true };
  const v = value.trim();
  if (v === '') return null;
  if (endpointFormatError(mode, v) !== null) return null;
  return mode === 'host' ? { host: v } : { network: v };
}

function endpointFormatError(mode: EndpointMode, value: string): string | null {
  if (value === '') return null;
  if (mode === 'host' && value.includes('/')) {
    return 'A single host, no /prefix — use Network for a CIDR range.';
  }
  if (mode === 'network' && !value.includes('/')) {
    return 'Needs a /prefix (e.g. /24) — use Host for a single IP.';
  }
  return null;
}

interface Props {
  value: RuleDraft[];
  onChange: (next: RuleDraft[]) => void;
  disabled?: boolean;
  fieldErrors?: Record<string, string> | null;
}

export function AclRuleEditor({ value, onChange, disabled, fieldErrors }: Props) {
  const addRule = () => onChange([...value, makeEmptyDraft()]);
  const removeRule = (idx: number) =>
    onChange(value.filter((_, i) => i !== idx));
  const patchRule = (idx: number, patch: Partial<RuleDraft>) =>
    onChange(value.map((r, i) => (i === idx ? { ...r, ...patch } : r)));

  return (
    <div className="flex flex-col gap-3">
      {value.length === 0 && (
        <p className="text-sm italic text-muted">No rules added.</p>
      )}
      {value.map((r, i) => (
        <RuleCard
          key={i}
          index={i}
          rule={r}
          disabled={disabled}
          error={rowError(fieldErrors, i)}
          onChange={(patch) => patchRule(i, patch)}
          onRemove={() => removeRule(i)}
        />
      ))}
      <div>
        <button
          type="button"
          onClick={addRule}
          disabled={disabled}
          className="rounded-md border border-dashed border-panel-border px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-info hover:bg-panel-elev disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          + Add rule
        </button>
      </div>
    </div>
  );
}

function RuleCard({
  index,
  rule,
  disabled,
  error,
  onChange,
  onRemove,
}: {
  index: number;
  rule: RuleDraft;
  disabled?: boolean;
  error?: string | null;
  onChange: (patch: Partial<RuleDraft>) => void;
  onRemove: () => void;
}) {
  const validity = useMemo(() => draftToRule(rule), [rule]);

  return (
    <div className="rounded-md border border-panel-border bg-panel-elev/40 p-3 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted">
          Rule {index + 1}
          {validity === null && (
            <span className="ml-2 text-danger normal-case">incomplete</span>
          )}
        </span>
        <button
          type="button"
          onClick={onRemove}
          disabled={disabled}
          aria-label={`Remove rule ${index + 1}`}
          className="text-danger hover:brightness-125 disabled:opacity-40 disabled:cursor-not-allowed text-lg leading-none"
        >
          ×
        </button>
      </div>

      <FieldError message={error ?? undefined} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <FieldRow label="Action">
          <select
            value={rule.action}
            onChange={(e) =>
              onChange({ action: e.target.value as 'permit' | 'deny' })
            }
            disabled={disabled}
            className="w-full rounded-md bg-panel-elev border border-panel-border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-info"
          >
            <option value="permit">permit</option>
            <option value="deny">deny</option>
          </select>
        </FieldRow>
        <FieldRow label="Protocol">
          <input
            type="text"
            value={rule.protocol}
            onChange={(e) => onChange({ protocol: e.target.value })}
            disabled={disabled}
            placeholder="e.g. ip, tcp, udp, icmp, 47"
            className="w-full rounded-md bg-panel-elev border border-panel-border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-info"
          />
        </FieldRow>
      </div>

      <EndpointField
        label="Source"
        mode={rule.srcMode}
        value={rule.srcValue}
        onModeChange={(srcMode) => onChange({ srcMode })}
        onValueChange={(srcValue) => onChange({ srcValue })}
        disabled={disabled}
        formatError={endpointFormatError(rule.srcMode, rule.srcValue.trim())}
      />

      <EndpointField
        label="Destination"
        mode={rule.dstMode}
        value={rule.dstValue}
        onModeChange={(dstMode) => onChange({ dstMode })}
        onValueChange={(dstValue) => onChange({ dstValue })}
        disabled={disabled}
        formatError={endpointFormatError(rule.dstMode, rule.dstValue.trim())}
      />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <FieldRow label="Port operator">
          <select
            value={rule.portMode}
            onChange={(e) =>
              onChange({
                portMode: e.target.value as RuleDraft['portMode'],
                portValue: '',
                portValue2: '',
              })
            }
            disabled={disabled}
            className="w-full rounded-md bg-panel-elev border border-panel-border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-info"
          >
            <option value="none">none</option>
            <option value="eq">eq</option>
            <option value="range">range</option>
          </select>
        </FieldRow>
        <FieldRow label="Value">
          <input
            type="text"
            value={rule.portValue}
            onChange={(e) => onChange({ portValue: e.target.value })}
            disabled={disabled || rule.portMode === 'none'}
            placeholder={rule.portMode === 'range' ? 'range start' : 'e.g. 443'}
            className="w-full rounded-md bg-panel-elev border border-panel-border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-info disabled:opacity-40"
          />
        </FieldRow>
        <FieldRow label="Value 2">
          <input
            type="text"
            value={rule.portValue2}
            onChange={(e) => onChange({ portValue2: e.target.value })}
            disabled={disabled || rule.portMode !== 'range'}
            placeholder="range end"
            className="w-full rounded-md bg-panel-elev border border-panel-border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-info disabled:opacity-40"
          />
        </FieldRow>
      </div>
    </div>
  );
}

function EndpointField({
  label,
  mode,
  value,
  onModeChange,
  onValueChange,
  disabled,
  formatError,
}: {
  label: string;
  mode: EndpointMode;
  value: string;
  onModeChange: (m: EndpointMode) => void;
  onValueChange: (v: string) => void;
  disabled?: boolean;
  formatError?: string | null;
}) {
  return (
    <FieldRow label={label}>
      <div className="flex flex-col gap-2 md:flex-row md:items-center">
        <div className="flex items-center gap-3 text-sm">
          {(['any', 'host', 'network'] as EndpointMode[]).map((m) => (
            <label key={m} className="flex items-center gap-1 cursor-pointer">
              <input
                type="radio"
                name={`${label}-mode`}
                checked={mode === m}
                onChange={() => onModeChange(m)}
                disabled={disabled}
                className="accent-info"
              />
              {m}
            </label>
          ))}
        </div>
        <input
          type="text"
          value={value}
          onChange={(e) => onValueChange(e.target.value)}
          disabled={disabled || mode === 'any'}
          placeholder={
            mode === 'network' ? 'e.g. 192.0.2.0/24' : mode === 'host' ? 'e.g. 192.0.2.5' : ''
          }
          className="flex-1 rounded-md bg-panel-elev border border-panel-border px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-info disabled:opacity-40"
        />
      </div>
      <FieldError message={formatError ?? undefined} />
    </FieldRow>
  );
}
