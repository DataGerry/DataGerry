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
import { ChangeDetectionStrategy, Component, inject, Input, ViewEncapsulation } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import {
  LICENSE_TIER_FEATURES,
  LICENSE_TIER_FILTER_ORDER,
  LICENSE_TIER_LABELS,
  LicenseEdition,
  LicenseFeature,
  LicenseTier
} from '../../models/license.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Reasons the dialog closes, so the caller can react to the user's intent. */
export const LICENSE_CATALOG_MODAL_RESULT = {
  activate: 'activate',
  later: 'later'
} as const;

/** A single tier filter chip. */
interface TierFilterOption {
  tier: LicenseTier;
  label: string;
}

/** Total premium features in the catalogue — the top tier holds the full set. */
const TOTAL_PREMIUM_FEATURES = LICENSE_TIER_FEATURES[LicenseTier.Corporate].length;

/**
 * Welcome dialog shown on entering License Management for a locked edition. It frames the premium
 * feature catalogue and points the user at the activation flow on the page behind it.
 *
 * Presentational only: it embeds {@link LicenseFeatureCatalogComponent}. The primary action resolves
 * with `activate`, while "Maybe later", the close button and the backdrop all simply reveal the page.
 */
@Component({
  selector: 'cmdb-license-catalog-modal',
  templateUrl: './license-catalog-modal.component.html',
  styleUrls: ['./license-catalog-modal.component.scss'],
  standalone: false,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None
})
export class LicenseCatalogModalComponent {
  @Input() edition: LicenseEdition = LicenseEdition.Community;
  @Input() features: LicenseFeature[] = [];

  public readonly activeModal = inject(NgbActiveModal);

  /** Tier chips shown above the catalogue; `null` selection means "All tiers" (no filter). */
  public readonly tierFilters: TierFilterOption[] = LICENSE_TIER_FILTER_ORDER.map((tier) => ({
    tier,
    label: LICENSE_TIER_LABELS[tier]
  }));

  public selectedTier: LicenseTier | null = null;

  /* --------------------------------------------------- FUNCTIONS --------------------------------------------------- */

  /** Caption announcing how many premium features the selected tier unlocks (`null` while unfiltered). */
  public get filterSummary(): string | null {
    if (this.selectedTier === null) {
      return null;
    }

    const count = LICENSE_TIER_FEATURES[this.selectedTier].length;
    const label = LICENSE_TIER_LABELS[this.selectedTier];

    return `${label} includes ${count} of ${TOTAL_PREMIUM_FEATURES} premium features.`;
  }

  /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

  /** Selects a tier filter (or clears it with `null`) to highlight that tier's features in the catalogue. */
  public onSelectTier(tier: LicenseTier | null): void {
    this.selectedTier = tier;
  }

  /** Closes the dialog and reveals the activation flow on the License Management page. */
  public onActivate(): void {
    this.activeModal.close(LICENSE_CATALOG_MODAL_RESULT.activate);
  }

  /** Dismisses the dialog ("Maybe later", close button or backdrop). */
  public onDismiss(): void {
    this.activeModal.dismiss(LICENSE_CATALOG_MODAL_RESULT.later);
  }
}
