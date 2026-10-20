export type ScopeKind = 'device' | 'device_group' | 'site';
export type AssignmentRole = 'observer' | 'operator' | 'admin';

export interface OpDefinition {
  scope_kind: ScopeKind;
  min_role: AssignmentRole;
}

export const OP_MIN_ROLE = {
  read_device:                { scope_kind: 'device' as const,       min_role: 'observer' as const },
  edit_device:                { scope_kind: 'device' as const,       min_role: 'admin' as const },
  delete_device:              { scope_kind: 'device' as const,       min_role: 'admin' as const },
  register_device:            { scope_kind: 'site' as const,         min_role: 'admin' as const },
  move_device_same_site:      { scope_kind: 'device' as const,       min_role: 'operator' as const },
  move_device_cross_site:     { scope_kind: 'site' as const,         min_role: 'admin' as const },
  retry_rollback:             { scope_kind: 'device' as const,       min_role: 'operator' as const },
  cancel_job:                 { scope_kind: 'device' as const,       min_role: 'operator' as const },
  read_group:                 { scope_kind: 'device_group' as const, min_role: 'observer' as const },
  list_group_devices:         { scope_kind: 'device_group' as const, min_role: 'observer' as const },
  create_group:               { scope_kind: 'site' as const,         min_role: 'admin' as const },
  edit_group:                 { scope_kind: 'device_group' as const, min_role: 'admin' as const },
  delete_group:               { scope_kind: 'device_group' as const, min_role: 'admin' as const },
  read_site:                  { scope_kind: 'site' as const,         min_role: 'observer' as const },
  edit_site:                  { scope_kind: 'site' as const,         min_role: 'admin' as const },
} as const;

export type Op = keyof typeof OP_MIN_ROLE;

export const ROLE_LEVEL: Record<AssignmentRole, number> = {
  observer: 1,
  operator: 2,
  admin: 3,
};
