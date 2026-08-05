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
import { HttpHeaders, HttpParams, HttpResponse } from "@angular/common/http";
import { Injectable } from "@angular/core";
import { Observable, map, catchError } from "rxjs";
import { ToastService } from "src/app/layout/toast/toast.service";
import { ApiCallService, ApiServicePrefix, resp } from "src/app/services/api-call.service";
import { CollectionParameters } from "src/app/services/models/api-parameter";
import { APIDeleteSingleResponse, APIGetMultiResponse } from "src/app/services/models/api-response";
import { WebhookLog } from "../models/WebhookLog.model";



@Injectable({
    providedIn: 'root',
})
export class WebhookLogService<T = any> implements ApiServicePrefix {
    public servicePrefix: string = 'webhook_events';

    public options = {
        headers: new HttpHeaders({
            'Content-Type': 'application/json',
        }),
        params: {},
        observe: resp,
    };

    constructor(private api: ApiCallService, private toast: ToastService) { }


    /**
     * Fetches all webhook Logs.
     */
    public getAllWebhooks(params: CollectionParameters = {
        filter: '',
        limit: 10,
        sort: 'public_id',
        order: 1,
        page: 1,
    }): Observable<APIGetMultiResponse<WebhookLog>> {
        const options = this.options;
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

        return this.api.callGet<APIGetMultiResponse<WebhookLog>>(`${this.servicePrefix}/`, options).pipe(
            map((apiResponse: HttpResponse<APIGetMultiResponse<WebhookLog>>) => apiResponse.body),
            catchError((error) => {
                this.toast.error(error?.error?.message)
                throw error;
            })
        );
    }


    /**
     * Deletes a webhookLog by its public ID.
     */
    public deleteWebhookLog(publicId: number): Observable<APIDeleteSingleResponse<T>> {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callDelete<APIDeleteSingleResponse<T>>(`${this.servicePrefix}/${publicId}`, options).pipe(
            map((apiResponse: HttpResponse<APIDeleteSingleResponse<T>>) => apiResponse.body),
            catchError((error) => {
                this.toast.error(error?.error?.message)
                throw error;
            })
        );
    }

}