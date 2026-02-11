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
import { HttpClient, HttpErrorResponse, HttpEvent, HttpHandler, HttpHeaders, HttpInterceptor, HttpParams, HttpRequest } from '@angular/common/http';

import { Observable, throwError, catchError } from 'rxjs';

import { ConnectionService } from '../modules/connect/services/connection.service';
/* ------------------------------------------------------------------------------------------------------------------ */

declare type HttpObserve = 'body' | 'events' | 'response';
export const resp: HttpObserve = 'response';

/* --------------------------------------------------- INTERFACES --------------------------------------------------- */

export interface ApiServicePrefix {
    servicePrefix: string;
}


export const httpObserveOptions = {
    headers: new HttpHeaders({
        'Content-Type': 'application/json'
    }),
    params: {},
    observe: resp
};


export const httpObservePostOptions = {
  headers: new HttpHeaders({
    'Content-Type': 'application/json'
  }),
  params: {},
  observe: resp
};


export const httpFileOptions = {
    headers: new HttpHeaders({}),
    params: {},
    observe: resp,
    responseType: 'blob'
};

/* ------------------------------------------------------------------------------------------------------------------ */

@Injectable({
  providedIn: 'root'
})
export class ApiCallService {

    private readonly apiPrefix = 'rest';
    private readonly apiURL: string;


    public static handleError(err: HttpErrorResponse) {
        if (err.error instanceof ErrorEvent) {
            console.error('An error occurred:', err.error.message);
        } else {
            console.error(
                `Backend returned code ${ err.status }, ` +
                `body was: ${ err.error }`
            );
        }
        return throwError(() => err);
    }


    constructor(private http: HttpClient, private connectionService: ConnectionService) {
        this.apiURL = `${ this.connectionService.getApiBaseUrl() }/${ this.apiPrefix }/`;
    }

/* -------------------------------------------------- HTTP METHODS -------------------------------------------------- */

    public callHead<T>(route: string, httpGetOptions: any = httpObserveOptions): Observable<any> {
        return this.http.head<T>(this.apiURL + route, httpGetOptions).pipe(catchError(ApiCallService.handleError));
    }


    public callGet<T>(route: string, httpGetOptions: any = httpObserveOptions): Observable<any> {
        return this.http.get<T>(this.apiURL + route, httpGetOptions).pipe(catchError(ApiCallService.handleError));
    }


    public callPost<T>(route: string, data, httpPostOptions: any = httpObserveOptions): Observable<any> {
        return this.http.post<T>(this.apiURL + route, data, httpPostOptions).pipe(catchError(ApiCallService.handleError));
    }


    public callPut<T>(route: string, data, httpPutOptions: any = httpObserveOptions): Observable<any> {
        return this.http.put<T>(this.apiURL + route, data, httpPutOptions).pipe(catchError(ApiCallService.handleError));
    }


    public callPatch<T>(route: string, data, httpPatchOptions: any = httpObserveOptions): Observable<any> {
        return this.http.patch<T>(this.apiURL + route, data, httpPatchOptions).pipe(catchError(ApiCallService.handleError));
    }


    public callDelete<T>(route: string, httpDeleteOptions: any = httpObserveOptions): Observable<any> {
        return this.http.delete<T>(this.apiURL + route, httpDeleteOptions).pipe(catchError(ApiCallService.handleError));
    }

    public callDeleteManyRoute<T>(route: string, params?: any): Observable<any> {
        /**
         * @deprecated @SD please refactor and remove this.
         */
        return this.http.delete<T>(this.apiURL + route, params);
    }


    public readCookies(name: string) {
        const result = new RegExp('(?:^|; )' + encodeURIComponent(name) + '=([^;]*)').exec(document.cookie);
        return result ? result[1] : 'true';
    }
}



export class HttpInterceptorHandler implements HttpHandler {
    constructor(private next: HttpHandler, private interceptor: HttpInterceptor) {

    }

    handle(req: HttpRequest<any>): Observable<HttpEvent<any>> {
        return this.interceptor.intercept(req, this.next);
    }
}


export class HttpProtocolHelper {
    /**
     * Creates a copy of the passing HTTP-Protocol with the desired http parameters
     * @param httpProtocol HTTP protocol
     * @param filter Evaluation which data should be fetched. (A generic query filter based)
     * @param limit The max number of resources returned (pageSize).
     * @param sort The query element which is used as the sort id (nested resources are possible via (.) dot).
     * @param order The order sequence in which `way` the sort should be returned.
     * @param page The current page. N number of elements will be skip based on (limit * page)
     */
    static createHttpProtocolOptions(
            httpProtocol,
            filter?: any,
            limit?: number,
            sort?: string,
            order?: number,
            page?: number) {

        const options = Object.assign(this, httpProtocol);

        let httpParams: HttpParams = new HttpParams();
        httpParams = httpParams.set('filter', filter === undefined || filter === 'undefined' ? undefined : filter);
        httpParams = httpParams.set('limit', limit === undefined ? '0' : limit.toString());
        httpParams = httpParams.set('sort', sort === undefined ? 'public_id' : sort);
        httpParams = httpParams.set('order', order === undefined ? '1' : order.toString());
        httpParams = httpParams.set('page', page === undefined ? '1' : page.toString());
        options.params = httpParams;

        return options;
    }
}