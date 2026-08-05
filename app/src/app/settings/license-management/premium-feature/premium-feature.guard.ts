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

import { LicenseFeature } from '../models/license.model';
import { PremiumFeatureService } from './premium-feature.service';

/**
 * Blocks a route when the active edition does not unlock the feature declared in `data.premiumFeature`,
 * presenting the upgrade modal instead of opening the page.
 *
 * Usage on a route:
 * ```
 * {
 *   path: 'ipam',
 *   canActivate: [AuthGuard, premiumFeatureGuard],
 *   data: { premiumFeature: LicenseFeature.Ipam }
 * }
 * ```
 */
export const premiumFeatureGuard: CanActivateFn = (route) => {
  const feature = route.data['premiumFeature'] as LicenseFeature | undefined;

  if (!feature) {
    return true;
  }

  return inject(PremiumFeatureService).ensureAccess(feature);
};
