/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2026 becon GmbH
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU Affero General Public License as
* published by the Free Software Foundation, either version 3 of the
* License, or (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU Affero General Public License for more details.
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { InjectionToken } from '@angular/core';
import { Observable } from 'rxjs';

import { MultiDataSectionSet } from '../../../models/cmdb-object';
import { CmdbMultiDataSection } from '../../../models/cmdb-type';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Validation verdict for a single candidate row being added/edited in the MDS modal.
 */
export interface MdsCandidateValidationState {
    /** True when the validator has no objection to the candidate row. */
    valid: boolean;
    /** User-facing error messages collected from the backend response. */
    errors: ReadonlyArray<string>;
}


export interface MdsRowValidatorOptions {
    /** Public id of the object being edited; null in object create mode. */
    excludeObjectId: number | null;
}


/**
 * Per-section runtime returned from {@link MdsRowValidator.attach} when a validator opts in.
 * The MDS component uses this to validate a row candidate from the add/edit modal *before*
 * the row gets committed to the table, so the user never sees a row in an invalid state.
 */
export interface MdsRowValidatorHandle {
    readonly errorAnchorField: string | null;

    /**
     * Validate a candidate row against the existing committed rows. The candidate object
     * is the modal form value keyed by field name. {@code editingRowId} carries the
     * multi_data_id of the row currently being edited (so the implementation can exclude
     * it from collision checks), or null when the user is adding a brand new row.
     */
    validateCandidate(
        currentRows: ReadonlyArray<MultiDataSectionSet>,
        candidate: Record<string, unknown>,
        editingRowId: number | null
    ): Observable<MdsCandidateValidationState>;

    /** Tear down subscriptions and resources. Called from MDS component ngOnDestroy. */
    destroy(): void;
}


/**
 * Plugin contract a feature can implement to participate in MDS row validation without
 * the generic MDS component needing to know about that feature.
 *
 * Return {@code null} from {@link attach} when the validator does not apply to the given
 * section so the MDS component can simply skip it.
 */
export interface MdsRowValidator {
    attach(
        section: CmdbMultiDataSection,
        options: MdsRowValidatorOptions
    ): MdsRowValidatorHandle | null;
}


/**
 * Multi-provider DI token. Register {@link MdsRowValidator} implementations against this
 * token to add row validation behavior; the MDS component picks them all up.
 */
export const MDS_ROW_VALIDATORS = new InjectionToken<ReadonlyArray<MdsRowValidator>>(
    'MdsRowValidators'
);


/** Seed state used when no validator has flagged anything. */
export const VALID_CANDIDATE_STATE: MdsCandidateValidationState = Object.freeze({
    valid: true,
    errors: Object.freeze([]) as ReadonlyArray<string>
});
