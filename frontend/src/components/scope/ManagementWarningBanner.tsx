import type { ManagementWarning } from './managementGuard';
import { ManagementNotice } from './ManagementNotice';

const MAX_ROWS = 6;

export function ManagementWarningBanner({ warnings }: { warnings: ManagementWarning[] }) {
  if (warnings.length === 0) return null;
  const shown = warnings.slice(0, MAX_ROWS);
  return (
    <ManagementNotice>
      <p className="font-semibold">Management access may be affected</p>
      <ul className="mt-1 space-y-0.5">
        {shown.map((w, i) => (
          <li key={`${w.device}/${w.interface}/${i}`}>
            <span className="font-mono">
              {w.device} · {w.interface}
            </span>{' '}
            {w.what} — VLAN {w.vlan} is the management VLAN of {w.device}.
          </li>
        ))}
        {warnings.length > MAX_ROWS && <li>…and {warnings.length - MAX_ROWS} more</li>}
      </ul>
      <p className="mt-1">A rollback cannot recover a path that is gone.</p>
    </ManagementNotice>
  );
}
