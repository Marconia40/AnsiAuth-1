'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
} from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';

export type SelectedScope =
  | { kind: 'all' }
  | { kind: 'site'; siteId: number };

interface ScopeContextValue {
  selectedScope: SelectedScope;
  setSelectedScope: (next: SelectedScope) => void;
}

const ScopeContext = createContext<ScopeContextValue | null>(null);

const QUERY_KEY = 'scope';
const STORAGE_KEY = 'ansiauth.scope';

function parseScope(raw: string | null): SelectedScope {
  if (!raw || raw === 'all') return { kind: 'all' };
  if (raw.startsWith('site:')) {
    const id = Number(raw.slice(5));
    if (Number.isFinite(id) && id > 0) return { kind: 'site', siteId: id };
  }
  return { kind: 'all' };
}

function stringifyScope(s: SelectedScope): string {
  return s.kind === 'all' ? 'all' : `site:${s.siteId}`;
}

export function ScopeProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const raw = searchParams.get(QUERY_KEY);
  const selectedScope = useMemo(() => parseScope(raw), [raw]);

  useEffect(() => {
    if (raw !== null) return;
    if (typeof window === 'undefined') return;
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (!stored || stored === 'all') return;
    const params = new URLSearchParams(searchParams.toString());
    params.set(QUERY_KEY, stored);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }, [raw, pathname, router, searchParams]);

  const setSelectedScope = useCallback(
    (next: SelectedScope) => {
      const str = stringifyScope(next);
      if (typeof window !== 'undefined') {
        window.localStorage.setItem(STORAGE_KEY, str);
      }
      const params = new URLSearchParams(searchParams.toString());
      if (next.kind === 'all') {
        params.delete(QUERY_KEY);
      } else {
        params.set(QUERY_KEY, str);
      }
      const query = params.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  const value = useMemo(
    () => ({ selectedScope, setSelectedScope }),
    [selectedScope, setSelectedScope],
  );

  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>;
}

export function useScope(): ScopeContextValue {
  const ctx = useContext(ScopeContext);
  if (ctx === null) {
    throw new Error('useScope must be used within a ScopeProvider');
  }
  return ctx;
}
