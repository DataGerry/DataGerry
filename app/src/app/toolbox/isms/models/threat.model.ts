export interface Threat {
    public_id?: number;
    name: string;
    source: number[];
    identifier: string;
    description: string;
  }

/**
 * Result of a bulk delete request for threats. Threats that are still
 * assigned to a Risk are reported in `in_use` and are not deleted.
 */
export interface ThreatBulkDeleteResult {
    successfully: number[];
    in_use: number[];
  }