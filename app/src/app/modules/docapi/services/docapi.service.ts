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
import { HttpParams, HttpResponse } from '@angular/common/http';
import { UntypedFormControl } from '@angular/forms';

import { Observable, timer, switchMap, map, catchError } from 'rxjs';

import { ApiCallService, ApiServicePrefix, httpFileOptions, httpObserveOptions } from '../../../services/api-call.service';

import { DocTemplate } from '../models/cmdb-doctemplate';
import { CollectionParameters } from '../../../services/models/api-parameter';
import { APIGetMultiResponse } from '../../../services/models/api-response';
/* ------------------------------------------------------------------------------------------------------------------ */

    export const checkDocTemplateExistsValidator = (docApiService: DocapiService<DocTemplate>, time: number = 500) => {
        return (control: UntypedFormControl) => {
            return timer(time).pipe(switchMap(() => {
                return docApiService.checkDocTemplateExists(control?.value).pipe(
                    map((response) => {
                        if(response?.body?.name == control?.value) {
                            return { docTemplateExists: true};
                        } else {
                            return null;
                        }
                    }),
                    catchError(() => {
                        return new Promise(resolve => {
                            resolve(null);
                        });
                    })
                );
            }));
        };
    };

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                   DOCAPI-SERVICE                                                   */
/* ------------------------------------------------------------------------------------------------------------------ */

@Injectable({
  providedIn: 'root'
})
export class DocapiService<T = DocTemplate> implements ApiServicePrefix {

    public readonly servicePrefix: string = 'docapi/template';
    public readonly newServicePrefix: string = 'docs/template';


    constructor(private api: ApiCallService) {

    }

/* -------------------------------------------------- CRUD - CREATE ------------------------------------------------- */

    public postDocTemplate(docInstance: DocTemplate): Observable<any> {
        const options = this.getBaseOptions();

        return this.api.callPost<DocTemplate>(this.servicePrefix + '/', docInstance, options);
    }

/* --------------------------------------------------- CRUD - READ -------------------------------------------------- */

    public getDocTemplateList(params: CollectionParameters = {
        filter: undefined,
        limit: 10,
        sort: 'public_id',
        order: 1,
        page: 1
    }): Observable<APIGetMultiResponse<T>> {
        const options = httpObserveOptions;
        let httpParams: HttpParams = new HttpParams();

        if (params.filter !== undefined) {
            const filter = JSON.stringify(params.filter);
            httpParams = httpParams.set('filter', filter);
        }

        httpParams = httpParams.set('limit', params.limit.toString());
        httpParams = httpParams.set('sort', params.sort);
        httpParams = httpParams.set('order', params.order.toString());
        httpParams = httpParams.set('page', params.page.toString());
        options.params = httpParams;

        return this.api.callGet<T>(`${ this.newServicePrefix }`, options).pipe(
            map((apiResponse: HttpResponse<APIGetMultiResponse<T>>) => {
                return apiResponse?.body;
            })
        );
    }


    public getObjectDocTemplateList(typeId: number): Observable<T[]> {
        const options = this.getBaseOptions();

        const searchfilter = {
            template_parameters: { type: typeId }
        };

        return this.api.callGet<T>(`${ this.servicePrefix }/by/${ JSON.stringify(searchfilter) }`, options).pipe(
            map((apiResponse) => {
                if (apiResponse?.status === 204) {
                    return [];
                }

                return apiResponse?.body;
            })
        );
    }


    public getRenderedObjectDoc(templateId: number, objectId: number) {
        return this.api?.callGet<any>(`${ this.servicePrefix }/${ templateId }/render/${ objectId }`, httpFileOptions);
    }


    public getDocTemplate(publicId: number) {
        const options = this.getBaseOptions();

        return this.api?.callGet<DocTemplate>(this.servicePrefix + '/' + publicId, options).pipe(
            map((apiResponse) => {
                if (apiResponse?.status === 204) {
                    return [];
                }

                return apiResponse?.body;
            })
        );
    }


    public checkDocTemplateExists(docName: string) {
        const options = this.getBaseOptions();

        return this.api?.callGet<T>(`${ this.servicePrefix }/name/${ docName }`, options);
    }

/* -------------------------------------------------- CRUD - UPDATE ------------------------------------------------- */

    public putDocTemplate(docInstance: DocTemplate): Observable<any> {
        const options = this.getBaseOptions();

        return this.api?.callPut(this.servicePrefix + '/', docInstance, options);
    }

/* -------------------------------------------------- CRUD - DELETE ------------------------------------------------- */

    public deleteDocTemplate(publicID: number) {
        const options = this.getBaseOptions();

        return this.api?.callDelete<number>(this.servicePrefix + '/' + publicID, options);
    }


/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    private getBaseOptions(){
        const options = httpObserveOptions;
        options.params = new HttpParams();

        return options;
    }
}
