'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { reauth, registerElevatedTokenProvider } from '@/services/api';
import { StepUpModal } from '@/components/StepUpModal';

interface StepUpContextValue {
  requireElevated: () => Promise<string>;
}

const StepUpContext = createContext<StepUpContextValue | null>(null);

type Waiter = {
  resolve: (token: string) => void;
  reject: (reason: unknown) => void;
};

export function StepUpProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const waitersRef = useRef<Waiter[]>([]);

  const requireElevated = useCallback((): Promise<string> => {
    return new Promise<string>((resolve, reject) => {
      waitersRef.current.push({ resolve, reject });
      setError(null);
      setOpen(true);
    });
  }, []);

  useEffect(() => registerElevatedTokenProvider(requireElevated), [requireElevated]);

  const settleAll = useCallback(
    (settle: (w: Waiter) => void) => {
      const drained = waitersRef.current;
      waitersRef.current = [];
      drained.forEach(settle);
    },
    [],
  );

  const handleSubmit = useCallback(
    async (password: string) => {
      setSubmitting(true);
      setError(null);
      try {
        await reauth(password);
        setOpen(false);
        settleAll((w) => w.resolve('ok'));
      } catch (err) {
        const detail =
          (err as { response?: { data?: { detail?: string; message?: string } } })?.response?.data
            ?.detail ??
          (err as { response?: { data?: { message?: string } } })?.response?.data?.message ??
          'Incorrect password';
        setError(String(detail));
      } finally {
        setSubmitting(false);
      }
    },
    [settleAll],
  );

  const handleCancel = useCallback(() => {
    setOpen(false);
    settleAll((w) => w.reject(new Error('reauth_cancelled')));
  }, [settleAll]);

  return (
    <StepUpContext.Provider value={{ requireElevated }}>
      {children}
      {open && (
        <StepUpModal
          submitting={submitting}
          error={error}
          onSubmit={handleSubmit}
          onCancel={handleCancel}
        />
      )}
    </StepUpContext.Provider>
  );
}

export function useStepUp(): StepUpContextValue {
  const ctx = useContext(StepUpContext);
  if (!ctx) throw new Error('useStepUp must be used inside StepUpProvider');
  return ctx;
}
