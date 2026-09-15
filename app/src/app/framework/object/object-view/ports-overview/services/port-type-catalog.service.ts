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

import { Observable, throwError } from 'rxjs';
import { catchError, map, shareReplay } from 'rxjs/operators';

import { CmdbType } from 'src/app/framework/models/cmdb-type';
import { SpecialType } from 'src/app/framework/models/special-type';
import { TypeService } from 'src/app/framework/services/type.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Both lookups end in a list of ids, so a type's fields and render metadata are left unread. */
const TYPE_ID_PROJECTION = { public_id: 1 };


/**
 * The type lists the port dialogs branch on, read once per session.
 *
 * They are configuration: asking again on every dialog repeats an answer that cannot have changed
 * while the user fills a form in. A caller that edits a type's markers drops the cache instead.
 */
@Injectable({ providedIn: 'root' })
export class PortTypeCatalogService {

    private readonly typeService = inject(TypeService);

    private readonly lookups = new Map<string, Observable<number[]>>();

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** Types that declare ports; only their objects can be an end of a cable. */
    public portCapableTypeIds(): Observable<number[]> {
        return this.typeIds('uses_ports', { uses_ports: true });
    }


    /** Types carrying the CABLE marker; only their objects can be an inventoried cable. */
    public cableTypeIds(): Observable<number[]> {
        return this.typeIds('cable', { special_type: SpecialType.CABLE });
    }


    /** Drops the cached lists, for a caller that has just changed which types carry a marker. */
    public invalidate(): void {
        this.lookups.clear();
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private typeIds(key: string, filter: Record<string, unknown>): Observable<number[]> {
        if (!this.lookups.has(key)) {
            this.lookups.set(key, this.readTypeIds(key, filter));
        }

        return this.lookups.get(key);
    }


    private readTypeIds(key: string, filter: Record<string, unknown>): Observable<number[]> {
        return this.typeService
            .getTypes({
                filter,
                projection: TYPE_ID_PROJECTION,
                limit: 0,
                sort: 'public_id',
                order: 1,
                page: 1
            })
            .pipe(
                map((response) => ((response?.results ?? []) as CmdbType[]).map((type) => type.public_id)),
                // A failed read is not kept, so the next dialog asks again instead of replaying it.
                catchError((err) => {
                    this.lookups.delete(key);

                    return throwError(() => err);
                }),
                shareReplay({ bufferSize: 1, refCount: false })
            );
    }
}
