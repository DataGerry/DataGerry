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

import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { ObjectService } from 'src/app/framework/services/object.service';

import { objectDisplayLabel } from '../utils/object-label.util';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Only the label is read; nothing else about the object says which device an interface sits on. */
const LABEL_PROJECTION = {
    'object_information.object_id': 1,
    'summary_line': 1,
    'type_information': 1
};


/**
 * Names the objects that hold the interface rows a port is linked to.
 *
 * The link routes answer with ids only, so without this the list reads "Object #68" where the picker
 * read "Server #68 - host-68". One request covers every object of a port, and a failure is not one:
 * the port rights do not imply access to the object on the other side, and the link still has to render.
 */
@Injectable({ providedIn: 'root' })
export class InterfaceObjectLabelService {

    private readonly objectService = inject(ObjectService);

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public labelsOf(objectIds: readonly number[]): Observable<Map<number, string>> {
        const unique = [...new Set(objectIds.filter((objectId) => objectId != null))];

        if (!unique.length) {
            return of(new Map<number, string>());
        }

        return this.objectService
            .getObjects({
                filter: [{ $match: { public_id: { $in: unique } } }],
                projection: LABEL_PROJECTION,
                limit: unique.length,
                sort: 'public_id',
                order: 1,
                page: 1
            })
            .pipe(
                map((response) => this.toLabelMap((response?.results ?? []) as RenderResult[])),
                catchError(() => of(new Map<number, string>()))
            );
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private toLabelMap(results: readonly RenderResult[]): Map<number, string> {
        const labels = new Map<number, string>();

        for (const result of results) {
            const objectId = result?.object_information?.object_id;

            if (objectId != null) {
                labels.set(objectId, objectDisplayLabel(result, objectId));
            }
        }

        return labels;
    }
}
