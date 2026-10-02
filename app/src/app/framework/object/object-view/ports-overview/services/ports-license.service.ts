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

import { Observable } from 'rxjs';
import { distinctUntilChanged, map } from 'rxjs/operators';

import { PremiumFeatureService } from 'src/app/settings/license-management/premium-feature/premium-feature.service';
import { PORTS_LICENSE_FEATURE, PortsAccess, portsAccessOf } from '../models/ports-license.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Port Connectivity's reading of the license; UX only, the backend refuses what is locked. */
@Injectable({ providedIn: 'root' })
export class PortsLicenseService {

    private readonly premiumFeature = inject(PremiumFeatureService);

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** Snapshot for templates; `LOCKED` until the license is known. */
    public access(): PortsAccess {
        return portsAccessOf(
            this.premiumFeature.isAvailable(PORTS_LICENSE_FEATURE),
            this.premiumFeature.isExpired()
        );
    }


    /** Waits for the license, then follows every change of it. */
    public access$(): Observable<PortsAccess> {
        return this.premiumFeature.entitlementChanges$().pipe(
            map(() => this.access()),
            distinctUntilChanged()
        );
    }
}
