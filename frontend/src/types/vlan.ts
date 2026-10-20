export interface VlanCreate {
  vlan_id: number;
  name: string;
  devices: string[];
}

export interface VlanUpdate {
  description: string;
  devices: string[];
}

export interface VlanDelete {
  devices: string[];
}

export interface VlanBatchChange {
  vlan_id: number;
  name?: string;
  eliminar?: boolean;
}

export interface VlanBatchRequest {
  changes: VlanBatchChange[];
  devices: string[];
}

export interface VlanEntry {
  vlan_id: number;
  name: string;
  description?: string;
}

export interface VlanJobResult {
  device: string;
  job_id: string;
}

export interface VlanOperationResult {
  group_job_id: string;
  jobs: VlanJobResult[];
}
