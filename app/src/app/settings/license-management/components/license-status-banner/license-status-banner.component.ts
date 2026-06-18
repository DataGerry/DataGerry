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
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

import { LicenseEdition, LicenseEntitlement } from '../../models/license.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Compact, at-a-glance license status banner shown at the top of the page. */
@Component({
  selector: 'cmdb-license-status-banner',
  templateUrl: './license-status-banner.component.html',
  styleUrls: ['./license-status-banner.component.scss'],
  standalone: false,
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class LicenseStatusBannerComponent {
  @Input() edition: LicenseEdition = LicenseEdition.Community;
  @Input() entitlement: LicenseEntitlement | null = null;
  @Input() remainingDays: number | null = null;

  public readonly LicenseEdition = LicenseEdition;

  /* --------------------------------------------------- FUNCTIONS --------------------------------------------------- */

  public get description(): string {
    switch (this.edition) {
      case LicenseEdition.SelfHosted:
        return 'All licensed features are active on this instance.';
      case LicenseEdition.Expired:
        return 'Licensed features are currently disabled.';
      default:
        return 'Core CMDB features are active.';
    }
  }

  public get remainingLabel(): string {
    if (this.remainingDays === null) {
      return 'No expiry';
    }

    if (this.remainingDays <= 0) {
      return 'Expired';
    }

    return `${this.remainingDays} day${this.remainingDays === 1 ? '' : 's'} remaining`;
  }
}
