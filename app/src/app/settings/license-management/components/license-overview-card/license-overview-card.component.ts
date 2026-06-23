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
  LICENSE_TIER_LABELS,
  LicenseEdition,
  LicenseEntitlement,
  LicenseFeature,
  LicenseTier
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

  /** Reveals the full license ID */
  public revealId = false;

  /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

  public toggleReveal(): void {
    this.revealId = !this.revealId;
  }

  /* --------------------------------------------------- FUNCTIONS --------------------------------------------------- */

  public get isComplete(): boolean {
    return this.variant === 'complete';
  }

  public get isExpired(): boolean {
    return this.edition === LicenseEdition.Expired;
  }

  /** Human-readable tier name from the entitlement `type`; falls back for an unknown discriminator. */
  public get tierLabel(): string {
    const type = this.entitlement?.type ?? '';
    return LICENSE_TIER_LABELS[type as LicenseTier] ?? 'Licensed';
  }

  /** Theme key driving the card treatment; `default` for any tier the UI does not theme explicitly. */
  public get tierKey(): string {
    const type = this.entitlement?.type ?? '';
    return (Object.values(LicenseTier) as string[]).includes(type) ? type : 'default';
  }

  /** Dark-surfaced tiers (Business/Corporate) carry white text and the white logo. */
  public get isDarkCard(): boolean {
    return this.tierKey === 'business' || this.tierKey === 'corporate' || this.tierKey === 'default';
  }

  /** Logo variant matched to the card surface: white knockout on dark tiers, full-color on light ones. */
  public get logoSrc(): string {
    return this.isDarkCard
      ? '/assets/img/RZ_Datagerry_RGB_w.svg'
      : '/assets/img/datagerry_logo.svg';
  }

  /** License key masked to the last four characters unless revealed (no payment-card grouping). */
  public get displayLicenseId(): string {
    const id = this.entitlement?.licenseId;

    if (!id) {
      return '—';
    }

    if (this.revealId) {
      return id;
    }

    return `•••• •••• ${id.replace(/-/g, '').slice(-4)}`;
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

  /** Tone class for the remaining-time value: red when lapsed, amber within a month, else neutral. */
  public get remainingTone(): string {
    if (this.remainingDays === null) {
      return 'is-perpetual';
    }

    if (this.remainingDays <= 0) {
      return 'is-expired';
    }

    return this.remainingDays <= 30 ? 'is-soon' : 'is-ok';
  }

  public featureLabel(feature: LicenseFeature): string {
    return LICENSE_FEATURE_LABELS[feature];
  }
}
