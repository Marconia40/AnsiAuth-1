export type JobStatus =
  | 'pending'
  | 'queued'
  | 'running'
  | 'retrying'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'rollback_performed';

export interface JobExecutionSummary {
  attempts: number | null;
  rollback_performed: boolean;
  rollback_success: boolean | null;
  duration_ms: number | null;
}

export interface Job {
  job_id: string;
  status: JobStatus;
  operation: string | null;
  parameters_summary: string | null;
  playbook: string | null;
  device: string | null;
  result: unknown;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  retry_count: number;
  max_retries: number;
  rollback_performed: boolean;
  rollback_success: boolean | null;
  pre_state: unknown;
  last_error: string | null;
  error_type: string | null;
  error_reason: string | null;
  error_summary: string | null;
  rollback_error: string | null;
  retry_rollback_jobs: RetryRollbackJobRef[];
  current_step: string | null;
  group_job_id: string | null;
  execution_summary: JobExecutionSummary | null;
}

export interface RetryRollbackJobRef {
  job_id: string;
  status: JobStatus;
  created_at: string | null;
  finished_at: string | null;
}

export const ACTIVE_JOB_STATUSES: JobStatus[] = ['pending', 'queued', 'running', 'retrying'];

export type GroupJobStatus = 'pending' | 'running' | 'completed' | 'partial_success' | 'partial_failure' | 'failed' | 'cancelled';

export interface GroupJobDeviceResult {
  device: string;
  job_id: string | null;
  status: string;
  current_step: string | null;
  retry_count: number;
  rollback_performed: boolean;
  rollback_success: boolean | null;
  error: string | null;
  error_type: string | null;
  error_reason: string | null;
  error_summary: string | null;
  rollback_error: string | null;
  duration_ms: number | null;
}

export interface GroupJobExecutionSummary {
  total_devices: number;
  completed: number;
  failed: number;
  cancelled: number;
  partial_success: boolean;
  rollback_count: number;
  duration_ms: number | null;
}

export interface GroupJob {
  group_job_id: string;
  status: GroupJobStatus;
  operation: string | null;
  playbook: string | null;
  parameters: Record<string, unknown> | null;
  parameters_summary: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  execution_summary: GroupJobExecutionSummary;
  device_results: GroupJobDeviceResult[];
}
