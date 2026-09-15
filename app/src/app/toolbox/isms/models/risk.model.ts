export interface Risk {
    public_id?: number;
    name: string;
    risk_type: string;
    identifier?: string;
    threats?: number[];
    vulnerabilities?: number[];
    protection_goals?: number[];
    description?: string;
    consequences?: string;
    category_id?: string;
  }

/**
 * Result of a bulk delete request for Risks. Deleting a Risk cascades to its
 * associated Risk Assessments and Control Measure Assignments; the counts of
 * those removed records are reported back so the outcome can be surfaced.
 */
export interface RiskBulkDeleteResult {
    successfully: number[];
    deleted_risk_assessments: number;
    deleted_control_measure_assignments: number;
  }