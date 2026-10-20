'use client';

import { useEffect, useRef } from 'react';
import { getLastActivity, markActivity } from '@/lib/sessionActivity';

const IDLE_LIMIT_MS = 14 * 60 * 1000;
const WARN_BEFORE_MS = 30 * 1000;
const POLL_INTERVAL_MS = 5_000;

const ACTIVITY_EVENTS: (keyof WindowEventMap)[] = [
  'mousemove',
  'keydown',
  'click',
  'scroll',
  'touchstart',
];

export interface IdleTimeoutCallbacks {
  onIdle: () => void;
  onWarn?: (secondsRemaining: number) => void;
  onResume?: () => void;
}

export function useIdleTimeout(
  enabled: boolean,
  { onIdle, onWarn, onResume }: IdleTimeoutCallbacks,
): void {
  const onIdleRef = useRef(onIdle);
  const onWarnRef = useRef(onWarn);
  const onResumeRef = useRef(onResume);

  useEffect(() => {
    onIdleRef.current = onIdle;
    onWarnRef.current = onWarn;
    onResumeRef.current = onResume;
  }, [onIdle, onWarn, onResume]);

  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return;

    markActivity('local');

    const handleActivity = () => markActivity('local');
    ACTIVITY_EVENTS.forEach((ev) =>
      window.addEventListener(ev, handleActivity, { passive: true }),
    );

    let warningActive = false;
    let firedIdle = false;

    const tick = () => {
      const idleFor = Date.now() - getLastActivity();

      if (idleFor >= IDLE_LIMIT_MS) {
        if (firedIdle) return;
        firedIdle = true;
        onIdleRef.current();
        return;
      }

      if (idleFor >= IDLE_LIMIT_MS - WARN_BEFORE_MS) {
        warningActive = true;
        const secondsLeft = Math.max(0, Math.ceil((IDLE_LIMIT_MS - idleFor) / 1000));
        onWarnRef.current?.(secondsLeft);
      } else if (warningActive) {
        warningActive = false;
        onResumeRef.current?.();
      }
    };

    tick();
    const interval = window.setInterval(tick, POLL_INTERVAL_MS);

    return () => {
      window.clearInterval(interval);
      ACTIVITY_EVENTS.forEach((ev) =>
        window.removeEventListener(ev, handleActivity),
      );
    };
  }, [enabled]);
}
