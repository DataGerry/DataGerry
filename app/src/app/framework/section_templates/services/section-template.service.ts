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
import { Injectable } from '@angular/core';
import { HttpHeaders, HttpParams, HttpResponse } from '@angular/common/http';

import { map } from 'rxjs/operators';
import { Observable } from 'rxjs';

import { ApiCallService, ApiServicePrefix, resp } from 'src/app/services/api-call.service';

import { CmdbSectionTemplate } from '../../models/cmdb-section-template';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { APIGetMultiResponse, APIUpdateSingleResponse } from 'src/app/services/models/api-response';
import { RenderResult } from '../../models/cmdb-render';
/* ------------------------------------------------------------------------------------------------------------------ */
export const COOCKIENAME = 'onlyActiveObjCookie';

type SectionTemplateRequestParams = Record<string, unknown> & {
    type?: string;
};

@Injectable({
    providedIn: 'root'
})
export class SectionTemplateService<T = CmdbSectionTemplate | RenderResult> implements ApiServicePrefix {
    public servicePrefix: string = 'section_templates';

    public readonly options = {
        headers: new HttpHeaders({
            'Content-Type': 'application/json'
        }),
        params: {},
        observe: resp
    };



    constructor(private api: ApiCallService) {}

/* -------------------------------------------------- CRUD - CREATE ------------------------------------------------- */

    /**
     * Creates and stores a CmdbSectionTemplate in the database
     * 
     * @param objectInstance (CmdbSectionTemplate): Section Template which should be crated
     * @returns Observable<any>
     */
    public postSectionTemplate(params: SectionTemplateRequestParams): Observable<any> {
        const sectionTemplateParams = this.withSectionTemplateType(params);
        let httpParams = new HttpParams();
    
        for (let key in sectionTemplateParams){
            let val:string = String(sectionTemplateParams[key]);
            httpParams = httpParams?.set(key, val);
        }

        this.options.params = httpParams;
    
        return this.api.callPost<CmdbSectionTemplate>(this.servicePrefix + '/', sectionTemplateParams, this.options).pipe(
            map((apiResponse) => {
                return apiResponse?.body;
            }),
        );
    }

/* --------------------------------------------------- CRUD - READ -------------------------------------------------- */

    /**
     * Get all section templates from backend
     * 
     * @param params optional params
     * @returns All section templates from backend
     */
    public getSectionTemplates(
        params: CollectionParameters = {
            filter: undefined, 
            limit: 0, 
            sort: 'public_id',
            order: 1, 
            page: 1, 
            projection: undefined 
        }): Observable<APIGetMultiResponse<T>> {
            const options = this.options;
            let httpParams: HttpParams = new HttpParams();

            if (params.filter !== undefined) {
                const filter = JSON.stringify(params.filter);
                httpParams = httpParams.set('filter', filter);
            }

            if (params.projection !== undefined) {
                const projection = JSON.stringify(params.projection);
                httpParams = httpParams.set('projection', projection);
            }

            httpParams = httpParams.set('limit', params.limit.toString());
            httpParams = httpParams.set('sort', params.sort);
            httpParams = httpParams.set('order', params.order.toString());
            httpParams = httpParams.set('page', params.page.toString());

            httpParams = httpParams.set('onlyActiveObjCookie', this.api.readCookies(COOCKIENAME));
            options.params = httpParams;

            return this.api.callGet<Array<T>>(this.servicePrefix + '/', options).pipe(
                map((apiResponse: HttpResponse<APIGetMultiResponse<T>>) => {
                    return apiResponse.body;
                })
            );
    }


    /**
     * Retrieves a single section template from database
     * @param publicID PublicID of section template
     * @returns Section template with the given publicID
     */
    public getSectionTemplate<R>(publicID: number): Observable<R> {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callGet<R[]>(`${ this.servicePrefix }/${ publicID }`, options).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            })
        );
    }


    public getGlobalSectionTemplateCount<R>(publicID: number): Observable<R>{
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callGet<R[]>(`${ this.servicePrefix }/${ publicID }/count`, options).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            })
        );
    }

/* -------------------------------------------------- CRUD - UPDATE ------------------------------------------------- */

    /**
     * Updates a CmdbLocation in the database
     * 
     * @param publicID (int): public_id of the location
     * @param objectInstance (CmdbLocation): the data which should be updated
     * @param httpOptions httpObserveOptions
     * @returns Observable<any>
     */
    public updateSectionTemplate(params: SectionTemplateRequestParams): Observable<any> {

        const putOptions = this.options;
        const sectionTemplateParams = this.withSectionTemplateType(params);
        let httpParams = new HttpParams();

        for (let key in sectionTemplateParams){
          let val:string = String(sectionTemplateParams[key]);
          httpParams = httpParams.set(key, val);
        }

        putOptions.params = httpParams;

        return this.api.callPut<T>(`${ this.servicePrefix }/`, sectionTemplateParams, putOptions).pipe(
            map((apiResponse: HttpResponse<APIUpdateSingleResponse<T>>) => {
                return apiResponse.body;
            })
        );
    }

/* -------------------------------------------------- CRUD - DELETE ------------------------------------------------- */

    /**
     * Deletes a single section template
     * @param publicID publicID of section template which should be deleted
     * @returns acknowledged
     */
    public deleteSectionTemplate(publicID: number): Observable<any> {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callDelete(`${ this.servicePrefix }/${ publicID }`, options).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            }),
        );
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private withSectionTemplateType(params: SectionTemplateRequestParams): SectionTemplateRequestParams {
        return {
            ...params,
            type: params.type ?? 'section'
        };
    }
}
