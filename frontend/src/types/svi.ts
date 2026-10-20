export interface SVI {
  vlan_id: number;
  description: string | null;
  admin_up: boolean | null;
  operational_up: boolean | null;
  ipv4_address: string | null;
  ipv4_address_secondary: string[] | null;
  ipv6_address: string | null;
  acl_in: string | null;
  acl_out: string | null;
  dhcp_relay_servers: string[] | null;
}

export interface SVIListResponse {
  device: string;
  vendor: string | null;
  count: number;
  svis: SVI[];
  management_vlan: number | null;
}

export interface SVICreateRequest {
  vlan_id: number;
  description?: string | null;
}

export interface SVIDeleteRequest {
  vlan_id: number;
}

export interface SVIAdminStateUpdateRequest {
  vlan_id: number;
  enabled: boolean;
}

export interface SVIDescriptionUpdateRequest {
  vlan_id: number;
  description: string;
}

export interface SVIDescriptionClearRequest {
  vlan_id: number;
}

export interface SVIIpv4UpdateRequest {
  vlan_id: number;
  ipv4_address: string;
}

export interface SVIIpv4ClearRequest {
  vlan_id: number;
}

export interface SVIIpv6UpdateRequest {
  vlan_id: number;
  ipv6_address: string;
}

export interface SVIIpv6ClearRequest {
  vlan_id: number;
}

export type SVIAclDirection = 'in' | 'out';

export interface SVIAclUpdateRequest {
  vlan_id: number;
  direction: SVIAclDirection;
  acl_name: string;
}

export interface SVIAclClearRequest {
  vlan_id: number;
  direction: SVIAclDirection;
}

export interface SVIDhcpRelayAddRequest {
  vlan_id: number;
  server: string;
}

export interface SVIDhcpRelayRemoveRequest {
  vlan_id: number;
  server: string;
}

export interface SVIIpv4SecondaryAddRequest {
  vlan_id: number;
  address: string;
}

export interface SVIIpv4SecondaryRemoveRequest {
  vlan_id: number;
  address: string;
}

export interface SVIJobResult {
  device: string;
  job_id: string;
  status?: string;
}

export interface SVIOperationResult {
  group_job_id: string;
  jobs: SVIJobResult[];
}

export interface SVIBatchRequest {
  description?: string | null;
  admin_up?: boolean | null;
  ipv4_address?: string | null;
  ipv6_address?: string | null;
  acl_in?: string | null;
  acl_out?: string | null;
  dhcp_relay_add?: string | null;
  dhcp_relay_remove?: string | null;
  ipv4_secondary_add?: string | null;
  ipv4_secondary_remove?: string | null;
}

