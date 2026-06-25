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
import { HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { BaseApiService } from 'src/app/core/services/base-api.service';
import { ApiCallService } from 'src/app/services/api-call.service';
import { APIGetSingleResponse } from 'src/app/services/models/api-response';

import { CurrentLicense, CurrentLicenseResponse } from '../models/license.model';
import { mapCurrentLicenseResponse } from '../utils/license.util';
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
    return this.handleGetRequest<APIGetSingleResponse<CurrentLicenseResponse>>(`${this.servicePrefix}/current`)
      .pipe(map((response) => mapCurrentLicenseResponse(response.result)));
  }

  /**
   * Generates a fresh activation request and returns its Base64 blob as a plain string.
   *
   * Uses the `as_string=true` variant of the activation-request endpoint so the key can be shown,
   * copied and downloaded inside the wizard instead of forcing a browser file download.
   */
  public generateActivationKey(): Observable<string> {
    const options = {
      headers: new HttpHeaders({}),
      params: { as_string: 'true' },
      responseType: 'text'
    };

    return this.api.callGet<string>(`${this.servicePrefix}/activation-request`, options);
  }

  /** Uploads a license blob for verification and activation; returns the resulting license. */
  public importLicense(blob: string): Observable<CurrentLicense> {
    return this.handlePostRequest<APIGetSingleResponse<CurrentLicenseResponse>>(`${this.servicePrefix}/activate`, { blob })
      .pipe(map((response) => mapCurrentLicenseResponse(response.result)));
  }

  /** Removes the currently stored license, degrading the instance back to the Community edition. */
  public deleteCurrentLicense(): Observable<void> {
    return this.handleDeleteRequest<void>(`${this.servicePrefix}/current`);
  }
}
