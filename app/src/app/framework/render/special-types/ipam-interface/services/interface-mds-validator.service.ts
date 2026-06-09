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
import { Injectable, inject } from '@angular/core';
import { Observable, of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';

import { MultiDataSectionSet } from '../../../../models/cmdb-object';
import { CmdbMultiDataSection } from '../../../../models/cmdb-type';
import {
    MdsCandidateValidationState,
    MdsRowValidator,
    MdsRowValidatorHandle,
    MdsRowValidatorOptions,
    VALID_CANDIDATE_STATE
} from '../../../sections/multi-data-section/mds-row-validator';
import {
    IPAM_INTERFACE_FIELD_NAMES,
    IPAM_INTERFACE_REQUIRED_FIELDS,
    IPAM_INTERFACE_SECTION_NAME
} from '../models/interface-fields';
import {
    InterfaceRowPayload,
    InterfaceValidationRequest,
    InterfaceValidationResponse
} from '../models/interface-validation.types';
import { InterfaceIpamApiService } from './interface-ipam-api.service';
/* ------------------------------------------------------------------------------------------------------------------ */


/**
 * Implementation of {@link MdsRowValidator} for the dg-ipam-interface MDS section. Plugs
 * into the MDS component via the {@code MDS_ROW_VALIDATORS} multi-provider, so the generic
 * MDS component carries no IPAM-specific knowledge.
 */
@Injectable({ providedIn: 'root' })
export class InterfaceMdsValidatorService implements MdsRowValidator {

    private readonly api = inject(InterfaceIpamApiService);

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public attach(
        section: CmdbMultiDataSection,
        options: MdsRowValidatorOptions
    ): MdsRowValidatorHandle | null {
        if (section?.name !== IPAM_INTERFACE_SECTION_NAME) {
            return null;
        }

        const sectionFields = section.fields ?? [];
        for (const fieldName of IPAM_INTERFACE_REQUIRED_FIELDS) {
            if (!sectionFields.includes(fieldName)) {
                return null;
            }
        }

        return new InterfaceCandidateValidatorHandle(this.api, options.excludeObjectId);
    }
}


/**
 * Validates a single candidate row (the form value the user is composing in the add/edit
 * modal) against the rest of the section's committed rows.
 */
class InterfaceCandidateValidatorHandle implements MdsRowValidatorHandle {

    public readonly errorAnchorField: string = IPAM_INTERFACE_FIELD_NAMES.IP_ADDRESS;

    constructor(
        private readonly api: InterfaceIpamApiService,
        private readonly excludeObjectId: number | null
    ) {}


    public validateCandidate(
        currentRows: ReadonlyArray<MultiDataSectionSet>,
        candidate: Record<string, unknown>,
        editingRowId: number | null
    ): Observable<MdsCandidateValidationState> {
        const rows: InterfaceRowPayload[] = [];

        for (const row of currentRows ?? []) {
            if (editingRowId !== null && row.multi_data_id === editingRowId) {
                continue;
            }
            rows.push(this.toRowPayloadFromSet(row));
        }

        const candidateRowId = editingRowId ?? this.nextRowIndex(currentRows);
        rows.push(this.toRowPayloadFromValues(candidate, candidateRowId));

        const payload: InterfaceValidationRequest = {
            rows,
            exclude_object_id: this.excludeObjectId
        };

        return this.api.validateInterface(payload).pipe(
            map(response => this.toState(response)),
            catchError(() => of(VALID_CANDIDATE_STATE))
        );
    }


    public destroy(): void {
        /* no-op: handle holds no subscriptions */
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private toRowPayloadFromSet(set: MultiDataSectionSet): InterfaceRowPayload {
        let subnet: number | null = null;
        let ip: string | null = null;
        let type: string | null = null;

        for (const entry of set.data ?? []) {
            if (entry.name === IPAM_INTERFACE_FIELD_NAMES.SUBNET) {
                subnet = this.toObjectId(entry.value);
            } else if (entry.name === IPAM_INTERFACE_FIELD_NAMES.IP_ADDRESS) {
                ip = this.toTrimmedString(entry.value);
            } else if (entry.name === IPAM_INTERFACE_FIELD_NAMES.TYPE) {
                type = this.toTrimmedString(entry.value);
            }
        }

        return {
            row_index: set.multi_data_id,
            subnet_id: subnet,
            ip_address: ip,
            interface_type: type ?? 'ipv4'
        };
    }


    private toRowPayloadFromValues(
        values: Record<string, unknown>,
        rowIndex: number
    ): InterfaceRowPayload {
        return {
            row_index: rowIndex,
            subnet_id: this.toObjectId(values?.[IPAM_INTERFACE_FIELD_NAMES.SUBNET]),
            ip_address: this.toTrimmedString(values?.[IPAM_INTERFACE_FIELD_NAMES.IP_ADDRESS]),
            interface_type: this.toTrimmedString(values?.[IPAM_INTERFACE_FIELD_NAMES.TYPE]) ?? 'ipv4'
        };
    }


    private toState(response: InterfaceValidationResponse | null): MdsCandidateValidationState {
        if (!response || response.valid) {
            return VALID_CANDIDATE_STATE;
        }

        const messages: string[] = [];
        for (const err of response.errors ?? []) {
            if (err?.message) {
                messages.push(err.message);
            }
        }

        return {
            valid: false,
            errors: messages
        };
    }


    private nextRowIndex(currentRows: ReadonlyArray<MultiDataSectionSet>): number {
        let max = -1;
        for (const row of currentRows ?? []) {
            if (typeof row.multi_data_id === 'number' && row.multi_data_id > max) {
                max = row.multi_data_id;
            }
        }
        return max + 1;
    }


    private toObjectId(value: unknown): number | null {
        const numeric = Number(value);
        return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
    }


    private toTrimmedString(value: unknown): string | null {
        if (typeof value !== 'string') {
            return null;
        }

        const trimmed = value.trim();
        return trimmed.length > 0 ? trimmed : null;
    }
}
