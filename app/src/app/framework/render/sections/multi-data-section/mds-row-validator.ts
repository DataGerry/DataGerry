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
import { UntypedFormGroup } from '@angular/forms';
import { Observable } from 'rxjs';

import { MultiDataSectionSet } from '../../../models/cmdb-object';
import { CmdbMultiDataSection } from '../../../models/cmdb-type';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Snapshot of one validator's verdict on the current MDS row set.
 */
export interface MdsValidationState {
    /** True when the validator has no objection to the current row set. */
    valid: boolean;
    /** multi_data_id values the validator has flagged. Used to highlight invalid rows. */
    invalidRowIndices: ReadonlyArray<number>;
}


export interface MdsRowValidatorOptions {
    /** Public id of the object being edited; null in object create mode. */
    excludeObjectId: number | null;
}


/**
 * Per-section runtime returned from {@link MdsRowValidator.attach} when a validator opts in.
 */
export interface MdsRowValidatorHandle {
    /** Stream of validation state. Must emit a default valid state on subscribe. */
    state$: Observable<MdsValidationState>;
    /** Trigger validation against the current row set  */
    validate(rows: ReadonlyArray<MultiDataSectionSet>): void;
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
        form: UntypedFormGroup,
        section: CmdbMultiDataSection,
        options: MdsRowValidatorOptions
    ): MdsRowValidatorHandle | null;
}


/**
 * Multi-provider DI token. Register {@link MdsRowValidator} implementations against this
 * token to add row validation behavior; the MDS component picks them all up and merges
 * their state without changes to its own code.
 */
export const MDS_ROW_VALIDATORS = new InjectionToken<ReadonlyArray<MdsRowValidator>>(
    'MdsRowValidators'
);


/**
 * Default state used as the seed for new handles and as the merged result when no
 * validator has flagged anything.
 */
export const VALID_MDS_STATE: MdsValidationState = Object.freeze({
    valid: true,
    invalidRowIndices: Object.freeze([]) as ReadonlyArray<number>
});
