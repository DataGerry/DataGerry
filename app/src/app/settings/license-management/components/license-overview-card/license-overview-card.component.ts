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

import {
  LICENSE_FEATURE_LABELS,
  LicenseEdition,
  LicenseEntitlement,
  LicenseFeature
} from '../../models/license.model';
/* ------------------------------------------------------------------------------------------------------------------ */

export type LicenseSummaryVariant = 'summary' | 'complete';

@Component({
  selector: 'cmdb-license-overview-card',
  templateUrl: './license-overview-card.component.html',
  styleUrls: ['./license-overview-card.component.scss'],
  standalone: false,
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class LicenseOverviewCardComponent {
  @Input() edition: LicenseEdition = LicenseEdition.SelfHosted;
  @Input() entitlement: LicenseEntitlement | null = null;
  @Input() remainingDays: number | null = null;
  @Input() features: LicenseFeature[] = [];
  @Input() variant: LicenseSummaryVariant = 'summary';

  public readonly LicenseEdition = LicenseEdition;

  /* --------------------------------------------------- FUNCTIONS --------------------------------------------------- */

  public get isComplete(): boolean {
    return this.variant === 'complete';
  }

  public get isExpired(): boolean {
    return this.edition === LicenseEdition.Expired;
  }

  public get heading(): string {
    if (this.isComplete) {
      return 'Self-Hosted Edition activated';
    }

    return this.isExpired ? 'Expired license' : 'Active license';
  }

  public get tierLabel(): string {
    return 'Self-Hosted Edition';
  }

  public get remainingLabel(): string {
    if (this.remainingDays === null) {
      return 'Perpetual';
    }

    if (this.remainingDays <= 0) {
      return 'Expired';
    }

    return `${this.remainingDays} day${this.remainingDays === 1 ? '' : 's'}`;
  }

  public featureLabel(feature: LicenseFeature): string {
    return LICENSE_FEATURE_LABELS[feature];
  }
}
