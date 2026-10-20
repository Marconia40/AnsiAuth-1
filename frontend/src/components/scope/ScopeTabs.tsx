'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

export interface ScopeTab {
  label: string;
  segment: string;
  disabled?: boolean;
  disabledReason?: string;
}

export const STANDARD_TABS: ScopeTab[] = [
  { label: 'Dashboard', segment: '' },
  { label: 'VLAN', segment: 'vlan' },
  { label: 'PORTS', segment: 'ports' },
  { label: 'VIRTUAL-INTERFACES', segment: 'virtual-interfaces' },
  { label: 'GLOBAL_CONFIG', segment: 'global-config' },
];

export function ScopeTabs({
  base,
  tabs = STANDARD_TABS,
}: {
  base: string;
  tabs?: ScopeTab[];
}) {
  const pathname = usePathname();
  const normalizedBase = base === '/' ? '' : base.replace(/\/+$/, '');
  const rootHref = normalizedBase === '' ? '/' : normalizedBase;

  return (
    <div className="border-b border-panel-border flex items-end gap-1 -mb-px overflow-x-auto">
      {tabs.map((tab) => {
        const href = tab.segment ? `${normalizedBase}/${tab.segment}` : rootHref;
        const active = tab.segment
          ? pathname === href || pathname.startsWith(`${href}/`)
          : pathname === rootHref;

        if (tab.disabled) {
          return (
            <span
              key={tab.label}
              title={tab.disabledReason}
              className="px-4 py-2 text-xs font-semibold uppercase tracking-wider text-muted/60 cursor-not-allowed select-none"
            >
              {tab.label}
            </span>
          );
        }

        return (
          <Link
            key={tab.label}
            href={href}
            className={`px-4 py-2 text-xs font-semibold uppercase tracking-wider transition-colors border-b-2 ${
              active
                ? 'border-info text-text bg-panel/60'
                : 'border-transparent text-muted hover:text-text hover:bg-panel/40'
            }`}
          >
            {tab.label}
          </Link>
        );
      })}
    </div>
  );
}
