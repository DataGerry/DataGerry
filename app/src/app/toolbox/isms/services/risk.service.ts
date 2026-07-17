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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Injectable } from '@angular/core';
import { HttpHeaders, HttpParams, HttpResponse } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map, catchError } from 'rxjs/operators';

import { ApiServicePrefix, resp, ApiCallService } from 'src/app/services/api-call.service';
import {
    APIGetMultiResponse,
    APIInsertSingleResponse,
    APIUpdateSingleResponse,
    APIDeleteSingleResponse
} from 'src/app/services/models/api-response';

import { Risk, RiskBulkDeleteResult } from '../models/risk.model';
import { CollectionParameters } from 'src/app/services/models/api-parameter';

@Injectable({
    providedIn: 'root'
})
export class RiskService implements ApiServicePrefix {
    public servicePrefix: string = 'isms/risks';
    public options = {
        headers: new HttpHeaders({ 'Content-Type': 'application/json' }),
        params: {},
        observe: resp
    };

    constructor(
        private api: ApiCallService
    ) { }

    /**
     * Fetch a list of risks with pagination, filtering, sorting
     */
    public getRisks(params: CollectionParameters): Observable<APIGetMultiResponse<Risk>> {
        const httpParams = this.buildHttpParams(params);
        const options = { ...this.options, params: httpParams };

        return this.api.callGet<APIGetMultiResponse<Risk>>(`${this.servicePrefix}/`, options)
            .pipe(
                map((res: HttpResponse<APIGetMultiResponse<Risk>>) => res.body),
                catchError((error) => { throw error; })
            );
    }

    /**
     * Build HttpParams based on your CollectionParameters
     */
    private buildHttpParams(params: CollectionParameters): HttpParams {
        let httpParams = new HttpParams()
            .set('limit', params.limit.toString())
            .set('page', params.page.toString())
            .set('sort', params.sort)
            .set('order', params.order);


        if (params.filter) {
            httpParams = httpParams.set('filter', JSON.stringify(params.filter));
        }
        return httpParams;
    }

    /**
     * Create a risk
     */
    public createRisk(risk: Risk): Observable<APIInsertSingleResponse<Risk>> {
        const options = { ...this.options };
        return this.api.callPost<APIInsertSingleResponse<Risk>>(`${this.servicePrefix}/`, risk, options)
            .pipe(
                map((res: HttpResponse<APIInsertSingleResponse<Risk>>) => res.body),
                catchError((error) => { throw error; })
            );
    }

    /**
     * Update a risk
     */
    public updateRisk(id: number, risk: Risk): Observable<APIUpdateSingleResponse<Risk>> {
        const options = { ...this.options };
        return this.api.callPut<APIUpdateSingleResponse<Risk>>(
            `${this.servicePrefix}/${id}`,
            risk,
            options
        ).pipe(
            map((res: HttpResponse<APIUpdateSingleResponse<Risk>>) => res.body),
            catchError((error) => { throw error; })
        );
    }

    /**
     * Delete a risk
     */
    public deleteRisk(id: number): Observable<APIDeleteSingleResponse<Risk>> {
        const options = { ...this.options };
        return this.api.callDelete<APIDeleteSingleResponse<Risk>>(
            `${this.servicePrefix}/${id}`,
            options
        ).pipe(
            map((res: HttpResponse<APIDeleteSingleResponse<Risk>>) => res.body),
            catchError((error) => { throw error; })
        );
    }

    /**
     * Delete multiple Risks at once. Deleting a Risk cascades to its associated
     * Risk Assessments and Control Measure Assignments; the response reports the
     * deleted Risk ids together with the counts of cascaded records removed.
     * @param publicIds risk public ids to delete
     */
    public deleteRisks(publicIds: number[]): Observable<RiskBulkDeleteResult> {
        const options = { ...this.options };
        return this.api.callDelete<RiskBulkDeleteResult>(
            `${this.servicePrefix}/delete/${publicIds.join(',')}`,
            options
        ).pipe(
            map((res: HttpResponse<RiskBulkDeleteResult>) => res.body),
            catchError((error) => { throw error; })
        );
    }
}
