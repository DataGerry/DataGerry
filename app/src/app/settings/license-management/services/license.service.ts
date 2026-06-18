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
import { HttpHeaders, HttpResponse } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { BaseApiService } from 'src/app/core/services/base-api.service';
import { ApiCallService, resp } from 'src/app/services/api-call.service';
import { APIGetSingleResponse } from 'src/app/services/models/api-response';

import { CurrentLicense } from '../models/license.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Thin data layer for the on-premise license endpoints (`rest/license/*`).
 *
 * The endpoints return a 404 in cloud/local mode; callers must guard with the deployment mode
 * before invoking them. All business logic (edition resolution, feature mapping) lives in the
 * pure helpers in `license.util.ts`.
 */
@Injectable({ providedIn: 'root' })
export class LicenseService extends BaseApiService<CurrentLicense> {
  public servicePrefix = 'license';

  constructor(protected api: ApiCallService) {
    super(api);
  }

  /* --------------------------------------------------- FUNCTIONS --------------------------------------------------- */

  /** Fetches the currently effective license (verified license, or the free fallback). */
  public getCurrentLicense(): Observable<CurrentLicense> {
    return this.handleGetRequest<APIGetSingleResponse<CurrentLicense>>(`${this.servicePrefix}/current`)
      .pipe(map((response) => response.result));
  }

  /**
   * Downloads the offline activation-request file generated and streamed by the backend.
   */
  public downloadActivationRequest(): Observable<HttpResponse<Blob>> {
    const options = {
      headers: new HttpHeaders({}),
      params: {},
      observe: resp,
      responseType: 'blob'
    };

    return this.api.callGet<Blob>(`${this.servicePrefix}/activation-request`, options);
  }

  /** Uploads a license blob for verification and activation; returns the resulting license. */
  public importLicense(blob: string): Observable<CurrentLicense> {
    return this.handlePostRequest<APIGetSingleResponse<CurrentLicense>>(`${this.servicePrefix}/activate`, { blob })
      .pipe(map((response) => response.result));
  }
}
