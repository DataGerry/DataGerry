import { Injectable } from '@angular/core';
import { HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

import { ApiCallService } from 'src/app/services/api-call.service';
import { BaseApiService } from 'src/app/core/services/base-api.service';
import { LicenseInfoResponse } from '../models/license.model';

@Injectable({ providedIn: 'root' })
export class LicenseService extends BaseApiService<any> {
  public servicePrefix = 'open_celium/licenses';

  constructor(protected api: ApiCallService) {
    super(api);
  }

  /** GET /licenses/info?page=0&size=5 */
  getLicenseInfo(page = 0, size = 5): Observable<LicenseInfoResponse> {
    const httpParams = new HttpParams()
      .set('page', page.toString())
      .set('size', size.toString());
    return this.handleGetRequest<LicenseInfoResponse>(`${this.servicePrefix}/info`, httpParams);
  }}