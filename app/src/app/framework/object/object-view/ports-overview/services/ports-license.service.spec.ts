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
import { TestBed } from '@angular/core/testing';

import { Subject } from 'rxjs';

import { LicenseFeature } from 'src/app/settings/license-management/models/license.model';
import { PremiumFeatureService } from 'src/app/settings/license-management/premium-feature/premium-feature.service';
import { PortsAccess, portsAccessOf } from '../models/ports-license.types';
import { PortsLicenseService } from './ports-license.service';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('portsAccessOf', () => {
    it('opens everything with a license', () => {
        expect(portsAccessOf(true, false)).toBe(PortsAccess.FULL);
    });

    it('keeps the existing ports on an expired license', () => {
        expect(portsAccessOf(false, true)).toBe(PortsAccess.LAPSED);
    });

    it('locks everything without a license', () => {
        expect(portsAccessOf(false, false)).toBe(PortsAccess.LOCKED);
    });
});


describe('PortsLicenseService', () => {
    let service: PortsLicenseService;
    let licensed: boolean;
    let expired: boolean;
    let changes: Subject<void>;

    beforeEach(() => {
        licensed = false;
        expired = false;
        changes = new Subject<void>();

        const premiumFeature = {
            isAvailable: (feature: LicenseFeature) => feature === LicenseFeature.Ipam && licensed,
            isExpired: () => expired,
            entitlementChanges$: () => changes
        };

        TestBed.configureTestingModule({
            providers: [{ provide: PremiumFeatureService, useValue: premiumFeature }]
        });

        service = TestBed.inject(PortsLicenseService);
    });

    it('reads the IPAM entitlement', () => {
        licensed = true;

        expect(service.access()).toBe(PortsAccess.FULL);
    });

    it('follows the license and skips repeats', () => {
        const seen: PortsAccess[] = [];
        service.access$().subscribe((access) => seen.push(access));

        changes.next();
        changes.next();
        expired = true;
        changes.next();
        licensed = true;
        changes.next();

        expect(seen).toEqual([PortsAccess.LOCKED, PortsAccess.LAPSED, PortsAccess.FULL]);
    });
});
