'use client';

import Link from 'next/link';
import { useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { getDevices } from '@/services/api';
import type { Device } from '@/types/device';
import { SearchIcon, XIcon } from './Icon';

const MAX_RESULTS = 20;

function matchDevices(devices: Device[], query: string): Device[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  return devices.filter((d) => d.name.toLowerCase().includes(q)).slice(0, MAX_RESULTS);
}

export function DeviceSearchBox() {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(0);
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);

  const { data } = useQuery<Device[]>({ queryKey: ['devices'], queryFn: getDevices });

  const matches = useMemo(() => matchDevices(data ?? [], query), [data, query]);

  function goTo(device: Device) {
    router.push(`/devices/${encodeURIComponent(device.name)}`);
    setQuery('');
    setOpen(false);
    inputRef.current?.blur();
  }

  function clear() {
    setQuery('');
    setOpen(false);
    inputRef.current?.focus();
  }

  return (
    <div className="relative px-2 pt-2 pb-1">
      <div className="relative">
        <SearchIcon
          size={14}
          className="absolute left-2 top-1/2 -translate-y-1/2 text-muted pointer-events-none"
        />
        <input
          ref={inputRef}
          type="search"
          value={query}
          placeholder="Search devices…"
          aria-label="Search devices"
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
            setHighlighted(0);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              clear();
            } else if (e.key === 'ArrowDown') {
              e.preventDefault();
              setHighlighted((i) => Math.min(i + 1, matches.length - 1));
            } else if (e.key === 'ArrowUp') {
              e.preventDefault();
              setHighlighted((i) => Math.max(i - 1, 0));
            } else if (e.key === 'Enter') {
              const target = matches[highlighted];
              if (target) goTo(target);
            }
          }}
          className="w-full pl-7 pr-7 py-1.5 text-sm rounded-md bg-panel-elev text-text placeholder:text-muted border border-panel-border focus:outline-none focus:ring-1 focus:ring-sidebar-active"
        />
        {query && (
          <button
            type="button"
            aria-label="Clear search"
            onMouseDown={(e) => e.preventDefault()}
            onClick={clear}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted hover:text-text"
          >
            <XIcon size={14} />
          </button>
        )}
      </div>

      {open && query.trim() !== '' && (
        <div className="absolute left-2 right-2 mt-1 z-10 max-h-80 overflow-y-auto rounded-md border border-panel-border bg-panel-elev shadow-lg">
          {matches.length === 0 ? (
            <p className="px-3 py-2 text-xs italic text-muted">No devices match &quot;{query}&quot;</p>
          ) : (
            matches.map((device, i) => (
              <Link
                key={device.name}
                href={`/devices/${encodeURIComponent(device.name)}`}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => goTo(device)}
                className={`block px-3 py-1.5 text-sm truncate ${
                  i === highlighted ? 'bg-sidebar-active text-white' : 'hover:bg-sidebar-hover text-text/90'
                }`}
              >
                <span className="font-medium">{device.name}</span>
                <span className="ml-2 text-xs text-muted">
                  {device.site_name} / {device.device_group_name}
                </span>
              </Link>
            ))
          )}
        </div>
      )}
    </div>
  );
}
