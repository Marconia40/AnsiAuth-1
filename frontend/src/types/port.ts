export type PortMode = 'access' | 'trunk' | 'unknown';
export type PortKind = 'physical' | 'aggregate';

export interface Port {
  name: string;
  name_full: string;
  description: string | null;
  admin_up: boolean | null;
  operational_up: boolean | null;
  mode: PortMode;
  kind: PortKind;
  access_vlan: number | null;
  allowed_vlans: number[] | null;
  storm_control_enabled: boolean | null;
  storm_control_threshold: number | null;
  storm_control_action: string | null;
  storm_control_trap: boolean | null;
}

export interface PortListResponse {
  device: string;
  vendor: string | null;
  count: number;
  ports: Port[];
  management_vlan: number | null;
}

export interface PortDescriptionUpdateRequest {
  interface: string;
  description: string;
}

export interface PortDescriptionClearRequest {
  interface: string;
}

export interface PortAdminStateUpdateRequest {
  interface: string;
  enabled: boolean;
}

export interface PortAccessVlanUpdateRequest {
  interface: string;
  vlan_id: number;
}

export type TrunkVlanMode = 'replace' | 'add' | 'remove';

export interface PortTrunkVlansUpdateRequest {
  interface: string;
  mode: TrunkVlanMode;
  vlans: number[];
}

export interface PortSetAccessModeRequest {
  interface: string;
  access_vlan: number;
}

export interface PortSetTrunkModeRequest {
  interface: string;
  native_vlan: number;
  allowed_vlans: number[];
}

export interface PortPoeUpdateRequest {
  interface: string;
  enabled: boolean;
}

export interface PortStormControlUpdateRequest {
  interface: string;
  enabled: boolean;
  threshold_percent?: number | null;
  action?: 'filter' | 'shutdown' | null;
  trap?: boolean | null;
}

export interface PortResetRequest {
  interface: string;
}

export interface PortJobResult {
  device: string;
  job_id: string;
  status?: string;
}

export interface PortOperationResult {
  group_job_id: string;
  jobs: PortJobResult[];
}

export interface PortBatchChangeItem {
  interface: string;
  description?: string | null;
  admin_up?: boolean | null;
  mode?: 'access' | 'trunk' | null;
  access_vlan?: number | null;
  allowed_vlans?: number[] | null;
  allowed_vlan_operation?: TrunkVlanMode;
  poe_enabled?: boolean | null;
  storm_control_enabled?: boolean | null;
  storm_control_threshold?: number | null;
  storm_control_action?: 'filter' | 'shutdown' | null;
  storm_control_trap?: boolean | null;
}

export interface PortBatchRequest {
  changes: PortBatchChangeItem[];
}

