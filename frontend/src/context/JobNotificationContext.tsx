'use client';

import { createContext, useContext, useState, useRef, useCallback, useEffect, type ReactNode } from 'react';
import { getJob, getGroupJob } from '@/services/api';
import type { GroupJobStatus, GroupJobDeviceResult } from '@/types/job';

export type JobNotification = {
  jobId: string;
  operation: string;
  device?: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  message: string;
  operationResult?: string;
  reason?: string;
};

export type GroupJobNotification = {
  groupJobId: string;
  label: string;
  status: GroupJobStatus;
  total: number;
  completed: number;
  failed: number;
  deviceResults: GroupJobDeviceResult[];
};

type JobNotificationContextValue = {
  jobs: JobNotification[];
  groupJobs: GroupJobNotification[];
  trackJob: (jobId: string, operation: string, device?: string) => void;
  trackGroupJob: (groupJobId: string, label: string) => void;
  dismissJob: (jobId: string) => void;
  dismissGroupJob: (groupJobId: string) => void;
};

const JobNotificationContext = createContext<JobNotificationContextValue | null>(null);

const JOB_POLL_INTERVAL_MS = 2500;
const DISMISS_DELAY_MS = 6000;

type PollerState = {
  poll: () => Promise<void>;
  timerId?: ReturnType<typeof setInterval>;
};

type DismissTimerState = {
  callback: () => void;
  remaining: number;
  timerId?: ReturnType<typeof setTimeout>;
  lastStartedAt?: number;
};

function stopInterval(state: PollerState): void {
  if (state.timerId !== undefined) {
    clearInterval(state.timerId);
    state.timerId = undefined;
  }
}

function startInterval(state: PollerState): void {
  if (state.timerId === undefined) {
    state.timerId = setInterval(state.poll, JOB_POLL_INTERVAL_MS);
  }
}

function pauseTimer(state: DismissTimerState): void {
  if (state.timerId !== undefined) {
    clearTimeout(state.timerId);
    state.timerId = undefined;
    if (state.lastStartedAt !== undefined) {
      const elapsed = Date.now() - state.lastStartedAt;
      state.remaining = Math.max(0, state.remaining - elapsed);
    }
  }
}

function resumeTimer(state: DismissTimerState): void {
  if (state.timerId !== undefined) return;
  if (state.remaining <= 0) {
    state.callback();
    return;
  }
  state.lastStartedAt = Date.now();
  state.timerId = setTimeout(state.callback, state.remaining);
}

export function JobNotificationProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<JobNotification[]>([]);
  const [groupJobs, setGroupJobs] = useState<GroupJobNotification[]>([]);

  const intervalsRef = useRef<Map<string, PollerState>>(new Map());
  const dismissTimersRef = useRef<Map<string, DismissTimerState>>(new Map());
  const groupIntervalsRef = useRef<Map<string, PollerState>>(new Map());
  const groupDismissTimersRef = useRef<Map<string, DismissTimerState>>(new Map());

  useEffect(() => {
    return () => {
      intervalsRef.current.forEach(stopInterval);
      dismissTimersRef.current.forEach((s) => {
        if (s.timerId !== undefined) clearTimeout(s.timerId);
      });
      groupIntervalsRef.current.forEach(stopInterval);
      groupDismissTimersRef.current.forEach((s) => {
        if (s.timerId !== undefined) clearTimeout(s.timerId);
      });
    };
  }, []);

  useEffect(() => {
    if (typeof document === 'undefined') return;

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        intervalsRef.current.forEach(stopInterval);
        groupIntervalsRef.current.forEach(stopInterval);
        dismissTimersRef.current.forEach(pauseTimer);
        groupDismissTimersRef.current.forEach(pauseTimer);
      } else {
        intervalsRef.current.forEach((state) => { void state.poll(); startInterval(state); });
        groupIntervalsRef.current.forEach((state) => { void state.poll(); startInterval(state); });
        dismissTimersRef.current.forEach(resumeTimer);
        groupDismissTimersRef.current.forEach(resumeTimer);
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, []);

  const dismissJob = useCallback((jobId: string) => {
    const state = intervalsRef.current.get(jobId);
    if (state !== undefined) { stopInterval(state); intervalsRef.current.delete(jobId); }
    const timer = dismissTimersRef.current.get(jobId);
    if (timer !== undefined) {
      if (timer.timerId !== undefined) clearTimeout(timer.timerId);
      dismissTimersRef.current.delete(jobId);
    }
    setJobs((prev) => prev.filter((n) => n.jobId !== jobId));
  }, []);

  const dismissGroupJob = useCallback((groupJobId: string) => {
    const state = groupIntervalsRef.current.get(groupJobId);
    if (state !== undefined) { stopInterval(state); groupIntervalsRef.current.delete(groupJobId); }
    const timer = groupDismissTimersRef.current.get(groupJobId);
    if (timer !== undefined) {
      if (timer.timerId !== undefined) clearTimeout(timer.timerId);
      groupDismissTimersRef.current.delete(groupJobId);
    }
    setGroupJobs((prev) => prev.filter((n) => n.groupJobId !== groupJobId));
  }, []);

  const trackJob = useCallback((jobId: string, operation: string, device?: string) => {
    setJobs((prev) => [
      { jobId, operation, device, status: 'pending', message: 'Pending...' },
      ...prev,
    ]);

    const poll = async () => {
      try {
        const job = await getJob(jobId);

        let status: JobNotification['status'];
        let message: string;
        let operationResult: string | undefined;
        let reason: string | undefined;

        if (job.status === 'completed') {
          status = 'completed';
          message = 'Completed successfully';
          const result = job.result as { operation_result?: string; reason?: string } | null;
          operationResult = result?.operation_result;
          reason = result?.reason;
        } else if (job.status === 'failed' || job.status === 'cancelled') {
          status = 'failed';
          message =
            job.error_summary ??
            job.error ??
            job.last_error ??
            (job.result as { message?: string } | null)?.message ??
            'Failed';
        } else if (job.status === 'running' || job.status === 'retrying') {
          status = 'running';
          message = job.status === 'retrying' ? 'Retrying...' : 'Running...';
        } else {
          status = 'pending';
          message = 'Pending...';
        }

        setJobs((prev) =>
          prev.map((n) =>
            n.jobId === jobId ? { ...n, status, message, operationResult, reason } : n,
          ),
        );

        if (status === 'completed' || status === 'failed') {
          const state = intervalsRef.current.get(jobId);
          if (state !== undefined) { stopInterval(state); intervalsRef.current.delete(jobId); }

          if (status === 'completed') {
            const dismissCb = () => {
              setJobs((prev) => prev.filter((n) => n.jobId !== jobId));
              dismissTimersRef.current.delete(jobId);
            };
            const timerState: DismissTimerState = {
              callback: dismissCb,
              remaining: DISMISS_DELAY_MS,
              lastStartedAt: Date.now(),
              timerId: setTimeout(dismissCb, DISMISS_DELAY_MS),
            };
            dismissTimersRef.current.set(jobId, timerState);
          }
        }
      } catch {
      }
    };

    const state: PollerState = { poll };
    startInterval(state);
    intervalsRef.current.set(jobId, state);
    void poll();
  }, []);

  const trackGroupJob = useCallback((groupJobId: string, label: string) => {
    setGroupJobs((prev) => [
      { groupJobId, label, status: 'pending', total: 0, completed: 0, failed: 0, deviceResults: [] },
      ...prev,
    ]);

    const poll = async () => {
      try {
        const gj = await getGroupJob(groupJobId);
        const { status, execution_summary, device_results } = gj;

        setGroupJobs((prev) =>
          prev.map((n) =>
            n.groupJobId === groupJobId
              ? {
                  ...n,
                  status,
                  total: execution_summary.total_devices,
                  completed: execution_summary.completed,
                  failed: execution_summary.failed,
                  deviceResults: device_results,
                }
              : n,
          ),
        );

        const isTerminal = status === 'completed' || status === 'partial_success' || status === 'failed' || status === 'cancelled';
        if (isTerminal) {
          const state = groupIntervalsRef.current.get(groupJobId);
          if (state !== undefined) { stopInterval(state); groupIntervalsRef.current.delete(groupJobId); }

          if (status === 'completed') {
            const dismissCb = () => {
              setGroupJobs((prev) => prev.filter((n) => n.groupJobId !== groupJobId));
              groupDismissTimersRef.current.delete(groupJobId);
            };
            const timerState: DismissTimerState = {
              callback: dismissCb,
              remaining: DISMISS_DELAY_MS,
              lastStartedAt: Date.now(),
              timerId: setTimeout(dismissCb, DISMISS_DELAY_MS),
            };
            groupDismissTimersRef.current.set(groupJobId, timerState);
          }
        }
      } catch {
      }
    };

    const state: PollerState = { poll };
    startInterval(state);
    groupIntervalsRef.current.set(groupJobId, state);
    void poll();
  }, []);

  return (
    <JobNotificationContext.Provider value={{ jobs, groupJobs, trackJob, trackGroupJob, dismissJob, dismissGroupJob }}>
      {children}
    </JobNotificationContext.Provider>
  );
}

export function useJobNotifications(): JobNotificationContextValue {
  const ctx = useContext(JobNotificationContext);
  if (!ctx) throw new Error('useJobNotifications must be used inside JobNotificationProvider');
  return ctx;
}
