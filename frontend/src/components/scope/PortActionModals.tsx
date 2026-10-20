'use client';

import { resetPort } from '@/services/api';
import { runPortBatch, type BatchResult } from './runPortBatch';
import { PortActionShell } from './PortActionShell';
import type { PortSelection } from './usePortSelection';
import type { Port } from '@/types/port';
import { anyPortCarriesManagement } from './managementGuard';
import { ManagementNotice } from './ManagementNotice';

interface Props {
  open: boolean;
  onClose: () => void;
  selection: PortSelection;
  portsByDevice: Map<string, Port[]>;
  managementVlanByDevice: Map<string, number | null>;
  onDone?: (result: BatchResult) => void;
}

function anySelectedPortUp(selection: PortSelection, portsByDevice: Map<string, Port[]>): boolean {
  for (const [device, ifaces] of selection.byDevice.entries()) {
    const ports = portsByDevice.get(device) ?? [];
    for (const iface of ifaces) {
      const port = ports.find((p) => p.name === iface);
      if (port?.admin_up === true) return true;
    }
  }
  return false;
}

export function PortResetModal({
  open,
  onClose,
  selection,
  portsByDevice,
  managementVlanByDevice,
  onDone,
}: Props) {
  const warnUp = anySelectedPortUp(selection, portsByDevice);
  const warnMgmt = anyPortCarriesManagement(selection.refs, portsByDevice, managementVlanByDevice);
  return (
    <PortActionShell
      open={open}
      onClose={onClose}
      title="Delete port config"
      selection={selection}
      actionLabel="Reset"
      tone="danger"
      onExecute={(progress) =>
        runPortBatch(
          selection.refs,
          (ref) => resetPort(ref.device, { interface: ref.interface }),
          { onProgress: progress },
        )
      }
      onDone={onDone}
    >
      <p className="text-sm text-warning border border-warning/40 bg-warning/10 rounded px-3 py-2">
        This wipes VLAN / description / PoE / storm-control back to the vendor
        default. Not reversible.
        {warnUp && (
          <>
            {' '}At least one selected port is currently up — resetting it will
            apply immediately and may drop whatever is connected.
          </>
        )}
      </p>
      {warnMgmt && (
        <ManagementNotice size="sm">
          At least one selected port carries the management VLAN of its device.
          Resetting it can cut management access, and a rollback cannot recover
          a path that is gone.
        </ManagementNotice>
      )}
    </PortActionShell>
  );
}
