import type { Role } from './auth';

export type AssignmentRole = 'observer' | 'operator' | 'admin';

export interface RoleAssignment {
  id: number;
  user_id: number;
  site_id: number;
  site_name: string | null;
  device_group_id: number | null;
  device_group_name: string | null;
  role: AssignmentRole;
  created_at: string;
  created_by_user_id: number | null;
  created_by_username: string | null;
}

export interface RoleAssignmentCreate {
  site_id: number;
  device_group_id?: number | null;
  role: AssignmentRole;
}

export interface SystemAdminUpdate {
  is_system_admin: boolean;
}

export interface User {
  id: number;
  username: string;
  email: string | null;
  is_active: boolean;
  is_system_admin: boolean;
  created_at: string;
  updated_at: string;
  role?: Role;
  reactivated?: boolean;
}

export interface UserCreate {
  username: string;
  password: string;
  email?: string;
  is_system_admin?: boolean;
  initial_grant?: RoleAssignmentCreate;
}

export interface UserUpdate {
  email?: string;
  is_active?: boolean;
  password?: string;
}
