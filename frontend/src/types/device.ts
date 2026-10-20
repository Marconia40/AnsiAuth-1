export type Vendor = 'cisco_ios' | 'huawei_vrp';

export type AuthMethod = 'password' | 'key';

export function vendorLabel(vendor: Vendor | string): string {
  if (vendor === 'cisco_ios') return 'Cisco';
  if (vendor === 'huawei_vrp') return 'Huawei';
  return vendor;
}

export interface Device {
  id: string;
  name: string;
  host: string;
  vendor: Vendor;
  platform: string;
  username: string;
  auth_method: AuthMethod;
  site_id: number;
  site_name: string;
  device_group_id: number;
  device_group_name: string;
}

export interface DeviceCreate {
  name: string;
  host: string;
  vendor: Vendor;
  platform: string;
  username: string;
  auth_method: AuthMethod;
  password?: string;
  private_key?: string;
  site_id: number;
  device_group_id?: number;
}

export interface DeviceUpdate {
  host?: string;
  vendor?: string;
  platform?: string;
  username?: string;
  auth_method?: AuthMethod;
  password?: string;
  private_key?: string;
}

export interface DeviceMove {
  device_group_id: number | null;
}
