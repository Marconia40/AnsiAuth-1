'use client';

import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { refreshDashboardScope } from '@/services/api';
import { scopeToSummaryParams, type Scope } from './ScopeDashboard';

export function useRefrescoAlAbrir(scope: Scope | null): void {
  const queryClient = useQueryClient();
  const clave = scope ? JSON.stringify(scopeToSummaryParams(scope)) : null;
  const ultimaClave = useRef<string | null>(null);

  useEffect(() => {
    if (!scope || !clave || ultimaClave.current === clave) return;
    ultimaClave.current = clave;
    refreshDashboardScope(scopeToSummaryParams(scope))
      .then(() => {
        queryClient.invalidateQueries({ queryKey: ['dashboard', 'summary'] });
        queryClient.invalidateQueries({ queryKey: ['vlans', 'synced'] });
        queryClient.invalidateQueries({ queryKey: ['ports', 'synced'] });
        queryClient.invalidateQueries({ queryKey: ['svis', 'synced'] });
      })
      .catch(() => {
      });
  }, [clave, scope, queryClient]);
}
