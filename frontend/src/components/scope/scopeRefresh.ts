import { refreshDeviceSync } from '@/services/api';

interface Options {
  onProgress?: (done: number, total: number) => void;
}

export async function runScopeRefresh(
  deviceNames: string[],
  options: Options = {},
): Promise<void> {
  const total = deviceNames.length;
  if (total === 0) return;

  let done = 0;
  await Promise.all(
    deviceNames.map(async (name) => {
      await refreshDeviceSync(name).catch(() => undefined);
      done += 1;
      options.onProgress?.(done, total);
    }),
  );
}
