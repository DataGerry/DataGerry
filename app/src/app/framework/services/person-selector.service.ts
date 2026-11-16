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
import { HttpHeaders, HttpParams } from '@angular/common/http';
import { Observable, forkJoin, map, of } from 'rxjs';

import { ApiCallService, resp } from '../../services/api-call.service';
import { PersonPickerPage, PersonPickerQuery, PersonSelection } from '../models/person-selector';
/* ------------------------------------------------------------------------------------------------------------------ */

/** The picker answers at most this many entries per page. */
const MAX_PAGE_LIMIT = 100;


@Injectable({ providedIn: 'root' })
export class PersonSelectorService {

    private readonly api = inject(ApiCallService);

    private readonly route = 'objects/selectable/persons';

    private readonly jsonHeaders = new HttpHeaders({ 'Content-Type': 'application/json' });

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** One page of the persons and person groups the user may select. */
    public getSelectablePersons(query: PersonPickerQuery): Observable<PersonPickerPage> {
        const options = {
            headers: this.jsonHeaders,
            params: this.toParams(query),
            observe: resp
        };

        return this.api
            .callGet<PersonPickerPage>(this.route, options)
            .pipe(map(response => response?.body as PersonPickerPage));
    }


    /** Labels of the given ids, keyed by id. Ids the user may not read are left out by the backend. */
    public resolvePersons(ids: ReadonlyArray<number>): Observable<Map<number, PersonSelection>> {
        const uniqueIds = [...new Set(ids)];

        if (!uniqueIds.length) {
            return of(new Map());
        }

        const requests: Observable<PersonPickerPage>[] = [];

        for (let start = 0; start < uniqueIds.length; start += MAX_PAGE_LIMIT) {
            requests.push(this.getSelectablePersons({
                ids: uniqueIds.slice(start, start + MAX_PAGE_LIMIT),
                limit: MAX_PAGE_LIMIT
            }));
        }

        return forkJoin(requests).pipe(
            map(pages => new Map(
                pages.flatMap(page => page?.results ?? []).map(selection => [selection.object_id, selection])
            ))
        );
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private toParams(query: PersonPickerQuery): HttpParams {
        let params = new HttpParams();

        if (query.kinds?.length) {
            params = params.set('kinds', query.kinds.join(','));
        }

        if (query.ids?.length) {
            params = params.set('ids', query.ids.join(','));
        } else if (query.search) {
            params = params.set('search', query.search);
        }

        if (query.page) {
            params = params.set('page', query.page);
        }

        if (query.limit) {
            params = params.set('limit', query.limit);
        }

        return params;
    }
}
