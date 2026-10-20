'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { AuthProvider } from '@/context/AuthContext';
import { JobNotificationProvider } from '@/context/JobNotificationContext';
import { StepUpProvider } from '@/context/StepUpContext';

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000,
            retry: 1,
            refetchOnWindowFocus: false,
            refetchIntervalInBackground: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <StepUpProvider>
          <JobNotificationProvider>{children}</JobNotificationProvider>
        </StepUpProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
