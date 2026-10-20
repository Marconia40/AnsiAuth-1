import { ScopeShell } from '@/components/scope/ScopeShell';
import type { ScopeTab } from '@/components/scope/ScopeTabs';
import { ScopeDashboard } from '@/components/scope/ScopeDashboard';
import { OrgHeaderActions } from '@/components/scope/OrgHeaderActions';

const ORG_TABS: ScopeTab[] = [
  { label: 'Dashboard', segment: '' },
  { label: 'VLAN', segment: 'vlan', disabled: true, disabledReason: 'Enable per-site or per-group' },
  { label: 'PORTS', segment: 'ports', disabled: true, disabledReason: 'Enable per-site or per-group' },
  {
    label: 'VIRTUAL-INTERFACES',
    segment: 'virtual-interfaces',
    disabled: true,
    disabledReason: 'Coming soon — backend endpoint pending',
  },
  {
    label: 'GLOBAL_CONFIG',
    segment: 'global-config',
    disabled: true,
    disabledReason: 'Coming soon — backend endpoint pending',
  },
];

export default function OrgDashboardPage() {
  return (
    <ScopeShell
      crumbs={[{ label: 'Management', href: '/' }]}
      tabsBase="/"
      tabs={ORG_TABS}
      actions={<OrgHeaderActions />}
    >
      <ScopeDashboard scope={{ kind: 'org' }} />
    </ScopeShell>
  );
}
