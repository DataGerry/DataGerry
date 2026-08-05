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
import { Observable } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import {
    APIGetMultiResponse,
    APIGetSingleResponse,
    APIInsertSingleResponse,
    APIDeleteSingleResponse,
    APIUpdateSingleResponse,
} from '../../services/models/api-response';
import { ApiCallService, ApiServicePrefix, resp } from '../../services/api-call.service';
import { CollectionParameters } from '../../services/models/api-parameter';
import { Webhook } from '../models/webhook.model';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { WebhookLog } from '../models/WebhookLog.model';

@Injectable({
    providedIn: 'root',
})
export class WebhookService<T = any> implements ApiServicePrefix {
    public servicePrefix: string = 'webhooks';

    public options = {
        headers: new HttpHeaders({
            'Content-Type': 'application/json',
        }),
        params: {},
        observe: resp,
    };

    constructor(private api: ApiCallService, private toast: ToastService) { }


    /**
     * Fetches webhook logs.
     */
    public getWebhookLogs(): Observable<WebhookLog[]> {
        return this.api.callGet<WebhookLog[]>(`${this.servicePrefix}/logs`, this.options).pipe(
            map((apiResponse: HttpResponse<WebhookLog[]>) => apiResponse.body),
            catchError((error) => {
                this.toast.error(error?.error?.message)
                throw error;
            })
        );
    }


    /**
     * Fetches all webhooks.
     */
    public getAllWebhooks(params: CollectionParameters = {
        filter: '',
        limit: 10,
        sort: 'public_id',
        order: 1,
        page: 1,
    }): Observable<APIGetMultiResponse<Webhook>> {
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

        return this.api.callGet<APIGetMultiResponse<Webhook>>(`${this.servicePrefix}/`, options).pipe(
            map((apiResponse: HttpResponse<APIGetMultiResponse<Webhook>>) => apiResponse.body),
            catchError((error) => {
                this.toast.error(error?.error?.message)
                throw error;
            })
        );
    }


    /**
     * Fetches a single webhook by its public ID.
     */
    public getWebhookById(publicId: number): Observable<APIGetSingleResponse<T>> {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callGet<APIGetSingleResponse<T>>(`${this.servicePrefix}/${publicId}`, options).pipe(
            map((apiResponse: HttpResponse<APIGetSingleResponse<T>>) => apiResponse.body),
            catchError((error) => {
                this.toast.error(error?.error?.message)
                throw error;
            })
        );
    }


    /**
     * Creates a new webhook.
     */
    public createWebhook(webhookData: {
        name: string;
        url: string;
        event_types: string[];
        active: boolean;
    }): Observable<APIInsertSingleResponse<T>> {
        let httpParams = new HttpParams();

        for (const key in webhookData) {
            const val: string = typeof webhookData[key] === 'object' ? JSON.stringify(webhookData[key]) : String(webhookData[key]);
            httpParams = httpParams.set(key, val);
        }

        this.options.params = httpParams;

        return this.api.callPost<APIInsertSingleResponse<T>>(`${this.servicePrefix}/`, webhookData, this.options).pipe(
            map((apiResponse: HttpResponse<APIInsertSingleResponse<T>>) => apiResponse.body),
            catchError((error) => {
                this.toast.error(error?.error?.message)
                throw error;
            })
        );
    }


    /**
     * Updates an existing webhook by its public ID.
     */
    public updateWebhook(publicId: number, webhookData: {
        public_id: number;
        name: string;
        url: string;
        event_types: string[];
        active: boolean;
    }): Observable<APIUpdateSingleResponse<T>> {
        // Construct query parameters
        let httpParams = new HttpParams()
            .set('public_id', String(publicId));

        for (const key in webhookData) {
            const val: string = typeof webhookData[key] === 'object' ? JSON.stringify(webhookData[key]) : String(webhookData[key]);
            httpParams = httpParams.set(key, val);
        }

        // Add httpParams to options
        const options = {
            ...this.options,
            params: httpParams,
        };

        const body = {
            ...webhookData,
            public_id: publicId, // Include public_id in the body
        };

        // Make the API call
        return this.api.callPut<APIUpdateSingleResponse<T>>(
            `${this.servicePrefix}/${publicId}`,
            body,
            options
        ).pipe(
            map((apiResponse: HttpResponse<APIUpdateSingleResponse<T>>) => apiResponse.body),
            catchError((error) => {
                this.toast.error(error?.error?.message)
                throw error;
            })
        );
    }


    /**
     * Deletes a webhook by its public ID.
     */
    public deleteWebhook(publicId: number): Observable<APIDeleteSingleResponse<T>> {
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
