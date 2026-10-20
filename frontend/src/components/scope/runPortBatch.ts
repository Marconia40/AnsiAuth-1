import type { PortBatchChangeItem, PortOperationResult } from '@/types/port';
import type { PortRef } from './usePortSelection';
import { parseFieldErrors } from '@/services/api';

export interface BatchResult {
  success: number;
  failed: number;
  errors: { ref: PortRef; error: string; fieldErrors?: Record<string, string> | null }[];
  groupJobsByDevice?: { device: string; groupJobId: string }[];
  perPortJobs?: { ref: PortRef; groupJobId: string }[];
}

interface Options {
  onProgress?: (done: number, total: number) => void;
  concurrency?: number;
}

function extractError(err: unknown): string {
  const e = err as {
    response?: { data?: { detail?: string; message?: string } };
    message?: string;
  } | null;
  return (
    e?.response?.data?.detail ??
    e?.response?.data?.message ??
    e?.message ??
    'Request failed'
  );
}

export async function runPortBatch(
  refs: PortRef[],
  executor: (ref: PortRef) => Promise<PortOperationResult>,
  { onProgress, concurrency = 6 }: Options = {},
): Promise<BatchResult> {
  const total = refs.length;
  let done = 0;
  const perPortJobs: { ref: PortRef; groupJobId: string }[] = [];
  const result: BatchResult = {
    success: 0,
    failed: 0,
    errors: [],
    perPortJobs,
  };

  let cursor = 0;
  async function worker() {
    while (true) {
      const idx = cursor++;
      if (idx >= total) return;
      const ref = refs[idx];
      try {
        const res = await executor(ref);
        result.success += 1;
        if (res?.group_job_id) perPortJobs.push({ ref, groupJobId: res.group_job_id });
      } catch (err) {
        result.failed += 1;
        result.errors.push({ ref, error: extractError(err), fieldErrors: parseFieldErrors(err) });
      } finally {
        done += 1;
        onProgress?.(done, total);
      }
    }
  }

  const workers = Array.from(
    { length: Math.min(concurrency, Math.max(1, total)) },
    worker,
  );
  await Promise.all(workers);
  return result;
}

export async function runPortBatchByDevice(
  byDevice: Map<string, string[]>,
  buildChange: (interfaceName: string) => Omit<PortBatchChangeItem, 'interface'>,
  executor: (device: string, changes: PortBatchChangeItem[]) => Promise<PortOperationResult>,
  { onProgress }: Options = {},
): Promise<BatchResult> {
  const total = Array.from(byDevice.values()).reduce((n, ifaces) => n + ifaces.length, 0);
  let done = 0;
  const groupJobsByDevice: { device: string; groupJobId: string }[] = [];
  const result: BatchResult = { success: 0, failed: 0, errors: [], groupJobsByDevice };

  for (const [device, interfaces] of byDevice) {
    const changes = interfaces.map((interfaceName) => ({
      interface: interfaceName,
      ...buildChange(interfaceName),
    }));
    try {
      const res = await executor(device, changes);
      result.success += interfaces.length;
      if (res?.group_job_id) {
        groupJobsByDevice.push({ device, groupJobId: res.group_job_id });
      }
    } catch (err) {
      result.failed += interfaces.length;
      const error = extractError(err);
      const fieldErrors = parseFieldErrors(err);
      for (const interfaceName of interfaces) {
        result.errors.push({ ref: { device, interface: interfaceName }, error, fieldErrors });
      }
    } finally {
      done += interfaces.length;
      onProgress?.(done, total);
    }
  }

  return result;
}
