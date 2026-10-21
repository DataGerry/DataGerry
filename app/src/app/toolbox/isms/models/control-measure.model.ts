export interface ControlMeasure {
    public_id?: number;
    title: string;
    control_measure_type: 'CONTROL' | 'REQUIREMENT' | 'MEASURE';
    source: number;                // references an Extendable Option of type CONTROL_MEASURE
    implementation_state: number;  // references an Extendable Option of type IMPLEMENTATION_STATE
    identifier?: string;
    chapter?: string;
    description?: string;
    is_applicable?: boolean;
    reason?: string;
  }

/**
 * Result of a bulk delete request for controls. Controls that are still
 * assigned to control measure assignments (CMAs) are reported in `in_use`
 * and are not deleted.
 */
export interface ControlMeasureBulkDeleteResult {
    successfully: number[];
    in_use: number[];
  }
