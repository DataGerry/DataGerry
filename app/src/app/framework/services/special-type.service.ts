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
import { HttpHeaders, HttpParams, HttpResponse } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable, map, shareReplay } from 'rxjs';
import { ApiCallService, ApiServicePrefix, resp } from 'src/app/services/api-call.service';
import { SpecialType, SpecialTypeSchema } from '../models/special-type';

@Injectable({
    providedIn: 'root'
})
export class SpecialTypeService implements ApiServicePrefix {

    public servicePrefix: string = 'special_types';

    private options = {
        headers: new HttpHeaders({
            'Content-Type': 'application/json'
        }),
        params: new HttpParams(),
        observe: resp
    };

    private schemaCache = new Map<SpecialType, Observable<SpecialTypeSchema>>();
    private schemaSnapshotCache = new Map<SpecialType, SpecialTypeSchema>();

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(private api: ApiCallService) {
    }

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public getAvailableSpecialTypes(): Observable<Record<string, string>> {
        const options = {
            ...this.options,
            params: new HttpParams().set('available', 'true')
        };

        return this.api.callGet<Record<string, string>>(`${this.servicePrefix}/`, options).pipe(
            map((response: HttpResponse<Record<string, string>>) => {
                return this.extractResponseBody<Record<string, string>>(response.body) ?? {};
            })
        );
    }


    public getSchema(specialType: SpecialType): Observable<SpecialTypeSchema> {
        if (!this.schemaCache.has(specialType)) {
            const options = {
                ...this.options,
                params: new HttpParams().set('special_type', specialType)
            };

            const schema$ = this.api.callGet<SpecialTypeSchema>(`${this.servicePrefix}/schema`, options).pipe(
                map((response: HttpResponse<SpecialTypeSchema>) => {
                    const schema = this.extractResponseBody<SpecialTypeSchema>(response.body);
                    this.schemaSnapshotCache.set(specialType, schema);
                    return schema;
                }),
                shareReplay(1)
            );

            this.schemaCache.set(specialType, schema$);
        }

        return this.schemaCache.get(specialType)!;
    }


    public getCachedSchema(specialType: SpecialType): SpecialTypeSchema | null {
        return this.schemaSnapshotCache.get(specialType) ?? null;
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private extractResponseBody<T>(responseBody: unknown): T {
        if (responseBody && typeof responseBody === 'object' && 'result' in responseBody) {
            return (responseBody as { result: T }).result;
        }

        return responseBody as T;
    }
}
