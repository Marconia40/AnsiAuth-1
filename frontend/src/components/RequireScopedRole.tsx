'use client';

import type { ReactNode } from 'react';
import { useCanPerform, type ScopeCoords } from '@/hooks/useAuthz';
import type { Op } from '@/constants/opMinRole';

interface Props {
  op: Op;
  scope: ScopeCoords | null;
  children: ReactNode;
  fallback?: ReactNode;
}

export function RequireScopedRole({
  op,
  scope,
  children,
  fallback = null,
}: Props) {
  const { allowed } = useCanPerform(op, scope);
  return <>{allowed ? children : fallback}</>;
}
