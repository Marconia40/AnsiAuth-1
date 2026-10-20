export type SiteKind = 'REGULAR' | 'BASE_INFRASTRUCTURE';

export interface Site {
  id: number;
  name: string;
  description: string | null;
  kind: SiteKind;
  default_group_id: number;
  created_at: string;
  updated_at: string;
  device_count: number;
}

export interface SiteCreate {
  name: string;
  description?: string;
}

export interface SiteUpdate {
  name?: string;
  description?: string;
}
