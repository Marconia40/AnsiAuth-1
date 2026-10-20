'use client';

import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { getDevice } from '@/services/api';
import type { Device } from '@/types/device';
import { ScopeShell } from '@/components/scope/ScopeShell';
import { useRefrescoAlAbrir } from '@/components/scope/useRefrescoAlAbrir';
import { STANDARD_TABS, type ScopeTab } from '@/components/scope/ScopeTabs';

const DEVICE_TABS: ScopeTab[] = STANDARD_TABS.map((tab) =>
  tab.segment === 'global-config'
    ? { label: tab.label, segment: tab.segment }
    : tab,
);

export default function DeviceScopeLayout({ children }: { children: ReactNode }) {
  const params = useParams<{ name: string }>();
  const rawName = params.name;
  const deviceName = typeof rawName === 'string' ? decodeURIComponent(rawName) : '';

  const { data: device } = useQuery<Device>({
    queryKey: ['device', deviceName],
    queryFn: () => getDevice(deviceName),
    enabled: Boolean(deviceName),
  });

  useRefrescoAlAbrir(deviceName ? { kind: 'device', deviceName } : null);

  const base = `/devices/${encodeURIComponent(deviceName)}`;

  return (
    <ScopeShell
      crumbs={[
        { label: 'Management', href: '/' },
        device
          ? { label: device.site_name, href: `/sites/${device.site_id}` }
          : { label: 'Site' },
        device
          ? { label: device.device_group_name, href: `/groups/${device.device_group_id}` }
          : { label: 'Group' },
        { label: deviceName || 'Device', href: base },
      ]}
      tabsBase={base}
      tabs={DEVICE_TABS}
    >
      {children}
    </ScopeShell>
  );
}
