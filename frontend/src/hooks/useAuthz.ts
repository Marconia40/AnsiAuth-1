'use client';

import { useQuery } from '@tanstack/react-query';
import { listGrants } from '@/services/api';
import { useAuth } from '@/context/AuthContext';
import { OP_MIN_ROLE, ROLE_LEVEL, type Op, type AssignmentRole } from '@/constants/opMinRole';
import type { RoleAssignment } from '@/types/user';

export type ScopeCoords =
  | { siteId: number; deviceGroupId?: number | null };

export function useMyGrants() {
  const { user } = useAuth();
  const enabled = user != null && typeof user.id === 'number' && !user.is_system_admin;
  return useQuery<RoleAssignment[]>({
    queryKey: ['grants-self', user?.id],
    queryFn: () => listGrants(user!.id!),
    enabled,
    staleTime: 60 * 1000,
  });
}

function effectiveRole(
  grants: RoleAssignment[],
  siteId: number,
  deviceGroupId: number | null | undefined,
): AssignmentRole | null {
  let siteWide: AssignmentRole | null = null;
  let groupSpecific: AssignmentRole | null = null;
  for (const g of grants) {
    if (g.site_id !== siteId) continue;
    if (g.device_group_id === null) {
      siteWide = g.role;
    } else if (deviceGroupId != null && g.device_group_id === deviceGroupId) {
      groupSpecific = g.role;
    }
  }
  if (deviceGroupId == null) return siteWide;
  const candidates = [siteWide, groupSpecific].filter(
    (r): r is AssignmentRole => r !== null,
  );
  if (candidates.length === 0) return null;
  return candidates.reduce((best, r) =>
    ROLE_LEVEL[r] > ROLE_LEVEL[best] ? r : best,
  );
}

export function useHasAnyAdminSite(): { loading: boolean; allowed: boolean } {
  const { user } = useAuth();
  const grantsQuery = useMyGrants();
  if (user?.is_system_admin) return { loading: false, allowed: true };
  if (grantsQuery.isLoading) return { loading: true, allowed: false };
  const anySiteAdmin = (grantsQuery.data ?? []).some(
    (g) => g.role === 'admin' && g.device_group_id === null,
  );
  return { loading: false, allowed: anySiteAdmin };
}

export interface CanPerformResult {
  loading: boolean;
  allowed: boolean;
  effectiveRole: AssignmentRole | 'super-admin' | null;
}

export function useCanPerform(op: Op, scope: ScopeCoords | null): CanPerformResult {
  const { user } = useAuth();
  const grantsQuery = useMyGrants();
  const def = OP_MIN_ROLE[op];

  if (user == null) {
    return { loading: false, allowed: false, effectiveRole: null };
  }
  if (user.is_system_admin) {
    return { loading: false, allowed: true, effectiveRole: 'super-admin' };
  }
  if (scope == null) {
    return { loading: false, allowed: false, effectiveRole: null };
  }
  if (grantsQuery.isLoading) {
    return { loading: true, allowed: false, effectiveRole: null };
  }
  const grants = grantsQuery.data ?? [];
  const groupIdForResolution =
    def.scope_kind === 'site' ? null : scope.deviceGroupId ?? null;
  const role = effectiveRole(grants, scope.siteId, groupIdForResolution);
  const allowed = role != null && ROLE_LEVEL[role] >= ROLE_LEVEL[def.min_role];
  return { loading: false, allowed, effectiveRole: role };
}
