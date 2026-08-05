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
import { Resolve } from '@angular/router';
import { Observable, of } from 'rxjs';
import { catchError, finalize, map } from 'rxjs/operators';

import { LoaderService } from 'src/app/core/services/loader.service';

import { CurrentLicense } from '../models/license.model';
import { LicenseService } from './license.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Outcome of the pre-navigation license fetch; `license` is null when the backend call failed. */
export interface ResolvedLicense {
  license: CurrentLicense | null;
  failed: boolean;
}

/**
 * Pre-fetches the current license before the License Management route activates, so the page never
 * renders before its data exists. The fetch is shielded with `catchError` so a backend failure still
 * lands on the page, where the component shows its error/retry state.
 */
@Injectable({ providedIn: 'root' })
export class LicenseResolver implements Resolve<ResolvedLicense> {
  constructor(
    private readonly licenseService: LicenseService,
    private readonly loaderService: LoaderService
  ) {}

  /* --------------------------------------------------- FUNCTIONS --------------------------------------------------- */

  public resolve(): Observable<ResolvedLicense> {
    this.loaderService.show();

    return this.licenseService.getCurrentLicense().pipe(
      map((license) => ({ license, failed: false })),
      catchError(() => of<ResolvedLicense>({ license: null, failed: true })),
      finalize(() => this.loaderService.hide())
    );
  }
}
