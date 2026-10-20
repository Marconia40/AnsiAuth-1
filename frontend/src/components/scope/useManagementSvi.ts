'use client';

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getSVIsSynced, type SyncedResource } from '@/services/api';
import type { SVIListResponse } from '@/types/svi';
import type { ManagementSvi } from './managementGuard';

export function useManagementSvi(deviceName: string): ManagementSvi | null {
  const query = useQuery<SyncedResource<SVIListResponse>>({
    queryKey: ['svis', 'synced', deviceName],
    queryFn: () => getSVIsSynced(deviceName),
    enabled: Boolean(deviceName),
  });
  const data = query.data?.data;
  return useMemo(() => {
    const vlan = data?.management_vlan ?? null;
    if (vlan === null || !data) return null;
    const svi = data.svis.find((s) => s.vlan_id === vlan);
    if (!svi) return null;
    return {
      vlan,
      subnets: [svi.ipv4_address, ...(svi.ipv4_address_secondary ?? [])].filter(
        (a): a is string => typeof a === 'string' && a !== '',
      ),
      aclIn: svi.acl_in,
      aclOut: svi.acl_out,
    };
  }, [data]);
}
