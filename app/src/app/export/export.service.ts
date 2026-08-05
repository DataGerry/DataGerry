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
import { HttpParams } from '@angular/common/http';

import { map } from 'rxjs';

import { ApiCallService, httpFileOptions } from '../services/api-call.service';

import { CollectionParameters } from '../services/models/api-parameter';
/* ------------------------------------------------------------------------------------------------------------------ */

@Injectable({
    providedIn: 'root'
})
export class FileService {
    private servicePrefix: string = 'exporter';

    constructor(private api: ApiCallService) {

    }

/* ------------------------------------------------- HELEPR METHODS ------------------------------------------------- */

    public callFileFormatRoute() {
        return this.api.callGet<any>(this.servicePrefix + '/extensions').pipe(
            map((apiResponse) => {
                return apiResponse.body;
            })
        );
    }


    public callExportRoute(params: CollectionParameters, view: string = 'native') {
        const options = httpFileOptions;
        let httpParams: HttpParams = new HttpParams();

        if (params.filter !== undefined) {
            httpParams = httpParams.set('filter', JSON.stringify(params.filter));
        }

        if (params.optional !== undefined) {
            const {classname, zip, metadata} = (params.optional as any);
            httpParams = httpParams.set('classname', classname);
            httpParams = httpParams.set('zip', zip);
            httpParams = httpParams.set('metadata', JSON.stringify(metadata));
        }

        httpParams = httpParams.set('sort', params.sort);
        httpParams = httpParams.set('order', params.order.toString());
        httpParams = httpParams.set('view', view);

        options.params = httpParams;

        return this.api.callGet<any>(this.servicePrefix + '/', options);
    }


    public getTypeFile() {
        return this.api.callPost<any>('export/type/', null, httpFileOptions);
    }


    public callExportTypeRoute(route: string) {
        return this.api.callPost<any>(route , null, httpFileOptions);
    }
}
