'use client';

import type { ReactNode } from 'react';
import { useAuth } from '@/context/AuthContext';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

export function RequireSystemAdmin({ children, fallback = null }: Props) {
  const { user } = useAuth();
  if (!user?.is_system_admin) return <>{fallback}</>;
  return <>{children}</>;
}
