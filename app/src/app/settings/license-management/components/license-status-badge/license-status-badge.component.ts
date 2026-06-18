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

import { LicenseEdition } from '../../models/license.model';
/* ------------------------------------------------------------------------------------------------------------------ */

interface BadgeView {
  label: string;
  icon: string;
}

/** Presentational status badge for the License Management header. */
@Component({
  selector: 'cmdb-license-status-badge',
  templateUrl: './license-status-badge.component.html',
  styleUrls: ['./license-status-badge.component.scss'],
  standalone: false,
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class LicenseStatusBadgeComponent {
  @Input() edition: LicenseEdition = LicenseEdition.Community;

  public readonly LicenseEdition = LicenseEdition;

  /* --------------------------------------------------- FUNCTIONS --------------------------------------------------- */

  public get view(): BadgeView {
    switch (this.edition) {
      case LicenseEdition.SelfHosted:
        return { label: 'Self-Hosted Edition', icon: 'fas fa-circle-check' };
      case LicenseEdition.Expired:
        return { label: 'Expired License', icon: 'fas fa-triangle-exclamation' };
      default:
        return { label: 'Community Edition', icon: 'fas fa-cube' };
    }
  }
}
