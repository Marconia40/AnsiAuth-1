export interface GlobalConfigSnmpInfo {
  enabled: boolean | null;
  version: string | null;
  community: string | null;
  permission: string | null;
  trap_hosts: string[] | null;
}

export interface GlobalConfigNtpInfo {
  servers: string[] | null;
}

export interface GlobalConfigDnsInfo {
  servers: string[] | null;
}

export interface GlobalConfigLoggingInfo {
  servers: string[] | null;
  level: string | null;
}

export interface GlobalConfigRouteEntry {
  destination?: string | null;
  next_hop?: string | null;
  interface?: string | null;
  [k: string]: unknown;
}

export interface GlobalConfigAclInfo {
  name: string;
  type: string | null;
  rules: string[];
}

export interface GlobalConfigRead {
  device: string;
  vendor: string | null;
  hostname: string | null;
  snmp: GlobalConfigSnmpInfo;
  ntp: GlobalConfigNtpInfo;
  dns: GlobalConfigDnsInfo;
  logging: GlobalConfigLoggingInfo;
  routes: GlobalConfigRouteEntry[] | null;
  acls: GlobalConfigAclInfo[] | null;
}

export interface GlobalConfigScopeDeviceEntry {
  device: string;
  vendor: string | null;
  hostname: string | null;
  snmp: GlobalConfigSnmpInfo;
  ntp: GlobalConfigNtpInfo;
  dns: GlobalConfigDnsInfo;
  logging: GlobalConfigLoggingInfo;
  routes: GlobalConfigRouteEntry[] | null;
  acls: GlobalConfigAclInfo[] | null;
  synced_at: string | null;
  sync_error: string | null;
  sync_in_progress: boolean;
}

export interface GlobalConfigVersionRead {
  device: string;
  vendor: string | null;
  software_version: string | null;
  model: string | null;
  uptime: string | null;
}

export interface GlobalConfigRunningConfigRead {
  device: string;
  vendor: string | null;
  running_config: string[] | null;
}

export type ArpMacEntry = Record<string, string | number | null>;

export interface ArpTableRead {
  device: string;
  vendor: string | null;
  entries: ArpMacEntry[] | null;
}

export interface MacTableRead {
  device: string;
  vendor: string | null;
  entries: ArpMacEntry[] | null;
}

export interface DeviceLogsRead {
  device: string;
  vendor: string | null;
  log_lines: string[] | null;
}

export interface HostnameUpdateRequest {
  hostname: string;
}

export interface SnmpUpdateRequest {
  version?: string;
  community?: string;
  trap_source?: string;
  trap_host?: string;
  trap_version?: string;
}

export interface LogServerAddRequest {
  server: string;
  level?: string;
}

export interface LogServerRemoveRequest {
  server: string;
}

export interface RouteAddRequest {
  destination: string;
  next_hop: string;
}

export type RouteRemoveRequest = RouteAddRequest;

export interface NtpAddRequest {
  server: string;
  prefer?: boolean;
}

export interface NtpRemoveRequest {
  server: string;
}

export interface DnsAddRequest {
  server?: string;
  domain_name?: string;
}

export interface DnsRemoveRequest {
  server: string;
}

export interface AclRuleEndpoint {
  any?: boolean;
  host?: string;
  network?: string;
}

export interface AclRulePort {
  operator: 'eq' | 'range';
  value: string;
  value2?: string;
}

export interface AclRule {
  action: 'permit' | 'deny';
  protocol: string;
  source: AclRuleEndpoint;
  destination: AclRuleEndpoint;
  port?: AclRulePort;
}

export interface AclCreateRequest {
  name: string;
  rules: AclRule[];
}

export type AclRuleRemoveRequest = AclCreateRequest;

export interface AclDeleteRequest {
  name: string;
}

export interface GlobalConfigJobResult {
  device: string;
  job_id: string;
  status?: string;
}

export interface GlobalConfigOperationResult {
  group_job_id: string;
  jobs: GlobalConfigJobResult[];
}
