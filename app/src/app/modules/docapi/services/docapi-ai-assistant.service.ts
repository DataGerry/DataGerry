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
import { Observable, map } from 'rxjs';

import { ApiCallService, ApiServicePrefix, httpObserveOptions } from '../../../services/api-call.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Injectable({
    providedIn: 'root'
})
export class DocapiAiAssistantService implements ApiServicePrefix {

    public readonly servicePrefix: string = 'chatgpt';

    constructor(private readonly api: ApiCallService) {
    }


    public generateHtml(message: string): Observable<string> {
        const options = this.getBaseOptions();

        return this.api.callPost<string>(`${this.servicePrefix}/message`, { message }, options).pipe(
            map((apiResponse: HttpResponse<unknown>) => {
                const responseBody = apiResponse?.body;

                if (typeof responseBody === 'string') {
                    return responseBody;
                }

                return responseBody ? String(responseBody) : '';
            })
        );
    }


    private getBaseOptions() {
        const options = httpObserveOptions;
        options.params = new HttpParams();

        return options;
    }
}
