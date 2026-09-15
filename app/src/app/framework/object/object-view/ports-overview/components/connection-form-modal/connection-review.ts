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
import { FieldOption } from 'src/app/framework/models/cmdb-section-template';

import { ConnectionEndpoint } from '../../models/port-connection.types';
import { describeEndpoint } from '../../utils/port-connection.util';

import { ConnectionForm } from './connection-form';
/* ------------------------------------------------------------------------------------------------------------------ */

/** One line of the review step. */
export interface ReviewRow {
    label: string;
    value: string;
}


/**
 * What the review step lists.
 *
 * A linked CI lists no cable values: they are not part of the write, and repeating them here would
 * claim the dialog is about to store something it does not send.
 */
/** The two ends, listed as plain review lines. */
export function buildEndpointRows(
    near: ConnectionEndpoint | null,
    far: ConnectionEndpoint | null
): ReviewRow[] {
    const rows: ReviewRow[] = [];

    pushRow(rows, 'This port', describeEndpoint(near));
    pushRow(rows, 'Far end', describeEndpoint(far));

    return rows;
}


export function buildReviewRows(
    form: ConnectionForm,
    cableTypeOptions: readonly FieldOption[],
    linkedCableLabel: string
): ReviewRow[] {
    const rows: ReviewRow[] = [{ label: 'Connection type', value: 'Cable' }];

    if (form.linksCableCi) {
        rows.push({ label: 'Cable', value: linkedCableLabel });
        rows.push({ label: 'Cable details', value: 'Taken from the linked cable' });

        return rows;
    }

    const cable = form.cableMetadata();

    pushRow(rows, 'Cable name', cable.cable_name);
    pushRow(rows, 'Cable type', labelOfCableType(cable.cable_type, cableTypeOptions));
    pushRow(rows, 'Length', cable.cable_length);
    pushRow(rows, 'Color', cable.cable_color);
    pushRow(rows, 'Description', cable.cable_description);
    rows.push({ label: 'Cable', value: 'Described here, not inventoried' });

    return rows;
}

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

/** An unanswered question is left out rather than listed as empty. */
function pushRow(rows: ReviewRow[], label: string, value: string | null): void {
    if (value) {
        rows.push({ label, value });
    }
}


/** The select binds option ids as strings, which is also how the catalog names them. */
function labelOfCableType(optionId: number | null, options: readonly FieldOption[]): string | null {
    if (optionId == null) {
        return null;
    }

    return options.find((option) => option.name === String(optionId))?.label ?? null;
}
