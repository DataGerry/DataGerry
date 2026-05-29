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
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { ApiCallService, resp } from '../../../../../services/api-call.service';
import {
    IpamSubnetOverviewParams,
    IpamSubnetOverviewResponse,
    IpamSupernetChildrenResponse,
    IpamSupernetInvalidSubnetsParams,
    IpamSupernetInvalidSubnetsResponse,
    IpamSupernetOverviewParams,
    IpamSupernetOverviewResponse,
    IpamUnassignSubnetsResponse
} from '../models/ipam-overview.types';
/* ------------------------------------------------------------------------------------------------------------------ */


@Injectable({ providedIn: 'root' })
export class IpamOverviewService {

    public servicePrefix: string = 'ipam';

    private readonly api = inject(ApiCallService);

    private readonly jsonHeaders = new HttpHeaders({ 'Content-Type': 'application/json' });

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public getSupernetOverview(
        publicId: number,
        params: IpamSupernetOverviewParams = {}
    ): Observable<IpamSupernetOverviewResponse> {
        const options = {
            headers: this.jsonHeaders,
            params: this.buildPagedParams(params),
            observe: resp
        };

        return this.api
            .callGet<IpamSupernetOverviewResponse>(`${this.servicePrefix}/supernet/overview/${publicId}`, options)
            .pipe(map(response => response?.body as IpamSupernetOverviewResponse));
    }


    public unassignSubnetsFromSupernet(
        supernetId: number,
        subnetIds: number[]
    ): Observable<IpamUnassignSubnetsResponse> {
        const options = {
            headers: this.jsonHeaders,
            params: {},
            observe: resp
        };

        return this.api
            .callPost<IpamUnassignSubnetsResponse>(
                `${this.servicePrefix}/supernet/overview/${supernetId}/subnets/unassign`,
                { subnet_ids: subnetIds },
                options
            )
            .pipe(map(response => response?.body as IpamUnassignSubnetsResponse));
    }


    public getInvalidSubnets(
        supernetId: number,
        params: IpamSupernetInvalidSubnetsParams = {}
    ): Observable<IpamSupernetInvalidSubnetsResponse> {
        const options = {
            headers: this.jsonHeaders,
            params: this.buildPagedParams(params),
            observe: resp
        };

        return this.api
            .callGet<IpamSupernetInvalidSubnetsResponse>(
                `${this.servicePrefix}/supernet/overview/${supernetId}/subnets/invalid`,
                options
            )
            .pipe(map(response => response?.body as IpamSupernetInvalidSubnetsResponse));
    }


    public getSupernetSubnetChildren(
        supernetId: number,
        subnetId: number
    ): Observable<IpamSupernetChildrenResponse> {
        const options = {
            headers: this.jsonHeaders,
            params: {},
            observe: resp
        };

        return this.api
            .callGet<IpamSupernetChildrenResponse>(
                `${this.servicePrefix}/supernet/overview/${supernetId}/subnets/children/${subnetId}`,
                options
            )
            .pipe(map(response => response?.body as IpamSupernetChildrenResponse));
    }


    public getSubnetOverview(
        publicId: number,
        params: IpamSubnetOverviewParams = {}
    ): Observable<IpamSubnetOverviewResponse> {
        const options = {
            headers: this.jsonHeaders,
            params: this.buildSubnetParams(params),
            observe: resp
        };

        return this.api
            .callGet<IpamSubnetOverviewResponse>(`${this.servicePrefix}/subnet/overview/${publicId}`, options)
            .pipe(map(response => response?.body as IpamSubnetOverviewResponse));
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private buildSubnetParams(params: IpamSubnetOverviewParams): HttpParams {
        return this.buildPagedParams(params);
    }

    private buildPagedParams(
        params: IpamSupernetOverviewParams | IpamSubnetOverviewParams | IpamSupernetInvalidSubnetsParams
    ): HttpParams {
        let httpParams = new HttpParams();

        if (params.page != null) {
            httpParams = httpParams.set('page', String(params.page));
        }
        if (params.page_size != null) {
            httpParams = httpParams.set('page_size', String(params.page_size));
        }
        if ('sort' in params && params.sort) {
            httpParams = httpParams.set('sort', params.sort);
        }
        if ('order' in params && params.order != null) {
            httpParams = httpParams.set('order', String(params.order));
        }
        if ('search' in params && params.search) {
            httpParams = httpParams.set('search', params.search);
        }

        return httpParams;
    }
}
