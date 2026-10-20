'use client';

import { useEffect } from 'react';

interface IdleWarningModalProps {
  secondsRemaining: number;
  onStay: () => void;
  onLogoutNow: () => void;
}

export function IdleWarningModal({
  secondsRemaining,
  onStay,
  onLogoutNow,
}: IdleWarningModalProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onStay();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onStay]);

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50"
      role="dialog"
      aria-modal="true"
      aria-labelledby="idle-warning-title"
    >
      <div className="w-full max-w-sm bg-panel rounded-lg shadow-xl p-6 space-y-4 mx-4">
        <div>
          <h2
            id="idle-warning-title"
            className="text-lg font-semibold text-gray-900"
          >
            Still there?
          </h2>
          <p className="mt-2 text-sm text-gray-600">
            Your session will end in{' '}
            <span className="font-semibold text-gray-900">
              {secondsRemaining}
              {secondsRemaining === 1 ? ' second' : ' seconds'}
            </span>{' '}
            due to inactivity.
          </p>
        </div>

        <div className="flex gap-2 justify-end pt-2">
          <button
            type="button"
            onClick={onLogoutNow}
            className="px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-md transition-colors"
          >
            Sign out now
          </button>
          <button
            type="button"
            onClick={onStay}
            autoFocus
            className="px-3 py-1.5 text-sm font-semibold text-white bg-[#2f4b7c] hover:bg-[#26406b] rounded-md transition-colors shadow-sm"
          >
            Stay signed in
          </button>
        </div>
      </div>
    </div>
  );
}
