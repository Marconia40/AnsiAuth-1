import type { ReactNode } from 'react';

export function ManagementNotice({
  children,
  size = 'xs',
  className = '',
}: {
  children: ReactNode;
  size?: 'xs' | 'sm';
  className?: string;
}) {
  return (
    <div
      role="note"
      className={`rounded-md border border-danger/50 bg-danger/10 px-3 py-2 text-danger ${
        size === 'sm' ? 'text-sm' : 'text-xs'
      } ${className}`.trim()}
    >
      {children}
    </div>
  );
}

export function ManagementTag({ title, className = '' }: { title: string; className?: string }) {
  return (
    <span
      className={`rounded border border-danger/50 bg-danger/10 px-1.5 py-0.5 font-sans text-[10px] uppercase tracking-wider text-danger ${className}`.trim()}
      title={title}
    >
      mgmt path
    </span>
  );
}
