export type Role = 'observer' | 'operator' | 'admin' | 'super-admin';

export interface AuthUser {
  id?: number;
  username: string;
  role: Role;
  is_system_admin: boolean;
  can_manage_users: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}
