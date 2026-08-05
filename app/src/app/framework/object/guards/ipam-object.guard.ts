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
import { inject } from '@angular/core';
import { CanActivateFn } from '@angular/router';
import { Observable, of } from 'rxjs';
import { catchError, map, switchMap, take } from 'rxjs/operators';

import { ObjectService } from 'src/app/framework/services/object.service';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { LicenseFeature } from 'src/app/settings/license-management/models/license.model';
import { PremiumFeatureService } from 'src/app/settings/license-management/premium-feature/premium-feature.service';

/**
 * Blocks view/edit/copy of IPAM special-type objects (subnets, supernets, …) when IPAM is not part of
 * the active edition, surfacing the upgrade modal instead.
 *
 * Entitled editions (Cloud / licensed Self-Hosted) short-circuit with no extra lookup. Only a locked
 * edition pays for the object lookup needed to discover whether the target is a special type. A blocked
 * navigation is simply cancelled (`false`) so the user stays on the page they came from while the
 * upsell modal is shown — no redirect.
 *
 * Frontend UX guard only — the backend must still reject these objects for unlicensed instances.
 */
export const ipamObjectGuard: CanActivateFn = (route): Observable<boolean> => {
  const premiumFeatureService = inject(PremiumFeatureService);
  const objectService = inject(ObjectService);

  return premiumFeatureService.isAvailable$(LicenseFeature.Ipam).pipe(
    take(1),
    switchMap((ipamAvailable) => {
      if (ipamAvailable) {
        return of(true);
      }

      const publicId = Number(route.paramMap.get('publicID'));
      if (!publicId) {
        return of(true);
      }

      return objectService.getObject<RenderResult>(publicId).pipe(
        map((render: RenderResult) => {
          const isSpecialTypeObject = !!render?.object_information?.special_type;

          if (!isSpecialTypeObject) {
            return true;
          }

          // Show the upsell and cancel the navigation in place — staying on the current page.
          premiumFeatureService.promptUpgrade(LicenseFeature.Ipam);
          return false;
        }),
        // A lookup failure shouldn't hard-block navigation; the backend remains the real gate.
        catchError(() => of(true))
      );
    })
  );
};
