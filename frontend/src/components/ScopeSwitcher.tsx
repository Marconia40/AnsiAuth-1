'use client';

import { useQuery } from '@tanstack/react-query';
import { getSites } from '@/services/api';
import { useAuth } from '@/context/AuthContext';
import { useScope } from '@/context/ScopeContext';
import type { Site } from '@/types/site';

export function ScopeSwitcher() {
  const { user } = useAuth();
  const { selectedScope, setSelectedScope } = useScope();
  const { data: sites, isLoading } = useQuery<Site[]>({
    queryKey: ['sites'],
    queryFn: getSites,
  });

  if (isLoading) {
    return (
      <span className="text-xs text-white/60 px-3">Viewing: …</span>
    );
  }

  const visibleSites = sites ?? [];
  if (visibleSites.length === 0) return null;

  if (visibleSites.length === 1 && !user?.is_system_admin) {
    return (
      <span
        className="text-xs text-white/85 bg-white/10 rounded-md px-3 py-1"
        title="You have access to a single site — the switcher is inactive."
      >
        Viewing: {visibleSites[0].name}
      </span>
    );
  }

  const currentValue =
    selectedScope.kind === 'site' ? String(selectedScope.siteId) : 'all';

  const currentSiteMissing =
    selectedScope.kind === 'site' &&
    !visibleSites.some((s) => s.id === selectedScope.siteId);

  return (
    <label className="flex items-center gap-2 text-xs text-white/85">
      <span className="hidden sm:inline text-white/60">Viewing:</span>
      <select
        value={currentSiteMissing ? 'all' : currentValue}
        onChange={(e) => {
          const v = e.target.value;
          setSelectedScope(v === 'all' ? { kind: 'all' } : { kind: 'site', siteId: Number(v) });
        }}
        className="bg-white/10 text-white rounded-md px-2 py-1 text-xs border border-white/20 focus:outline-none focus:ring-2 focus:ring-white/40"
      >
        <option value="all">All sites</option>
        {visibleSites.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
    </label>
  );
}
