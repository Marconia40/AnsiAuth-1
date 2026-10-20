'use client';

import { useEffect, useState } from 'react';
import { saveDeviceConfig } from '@/services/api';
import { useJobNotifications } from '@/context/JobNotificationContext';
import { extractMessage } from './VlanCreateModal';

const ERROR_MS = 5000;

export function SaveConfigButton({ deviceName }: { deviceName: string }) {
  const { trackGroupJob } = useJobNotifications();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!error) return;
    const t = setTimeout(() => setError(null), ERROR_MS);
    return () => clearTimeout(t);
  }, [error]);

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const result = await saveDeviceConfig(deviceName);
      trackGroupJob(result.group_job_id, `Save configuration on ${deviceName}`);
    } catch (err) {
      setError(extractMessage(err, 'Could not queue the save.'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={handleSave}
        disabled={saving}
        title="Writes the running configuration to the startup configuration (Cisco: write, Huawei: save). It saves everything running on the device, including changes made outside this app that were not saved yet, and a reload will no longer undo them."
        className="inline-flex items-center gap-2 rounded-md border border-panel-border bg-panel px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-text hover:bg-panel-elev disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {saving ? 'Saving…' : 'Save config'}
      </button>
      {error && (
        <div className="fixed bottom-4 right-4 z-40 rounded-md px-4 py-2 shadow-lg text-sm bg-danger text-white">
          {error}
        </div>
      )}
    </>
  );
}
