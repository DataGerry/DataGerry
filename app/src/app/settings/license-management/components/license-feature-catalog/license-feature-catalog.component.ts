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
  LicenseFeature
} from '../../models/license.model';
import {
  PREMIUM_CATALOG_CATEGORIES,
  PREMIUM_FEATURE_CONTENT,
  PREMIUM_FEATURED_FEATURE
} from '../../premium-feature/premium-feature.config';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Presentational view model for a single feature card. */
interface CatalogItem {
  feature: LicenseFeature;
  label: string;
  icon: string;
  description: string;
  /** Benefit points listed on the featured card. */
  benefits: string[];
  /** Rendered as the prominent, full-width "Featured capability" card. */
  featured: boolean;
}

/** A labelled group of features, used to make the catalogue scannable. */
interface CatalogSection {
  key: string;
  label: string;
  items: CatalogItem[];
}

/** Icon shown when a feature has no catalogue copy yet (defensive; every key currently has content). */
const FALLBACK_ICON = 'fas fa-cube';

/**
 * Catalogue of Self-Hosted premium features, grouped by category with one featured capability.
 *
 * Purely presentational and informational (cards are not selectable): copy comes from the shared
 * content registry and the `features` input decides whether a card reads as already enabled.
 */
@Component({
  selector: 'cmdb-license-feature-catalog',
  templateUrl: './license-feature-catalog.component.html',
  styleUrls: ['./license-feature-catalog.component.scss'],
  standalone: false,
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class LicenseFeatureCatalogComponent {
  @Input() edition: LicenseEdition = LicenseEdition.Community;

  /** Render the built-in section heading. Disable when a host (e.g. the upgrade dialog) supplies its own. */
  @Input() showHeader = true;

  /** Features unlocked by the active edition; drives the per-card enabled indicator. */
  @Input()
  set features(value: LicenseFeature[] | null) {
    this.unlocked = new Set(value ?? []);
  }

  public readonly sections: CatalogSection[] = this.buildSections();

  private unlocked = new Set<LicenseFeature>();

  /* --------------------------------------------------- FUNCTIONS --------------------------------------------------- */

  public get allUnlocked(): boolean {
    return this.edition === LicenseEdition.SelfHosted;
  }

  public get sectionTitle(): string {
    return 'Self-Hosted Features';
  }

  public get sectionSubtitle(): string {
    return this.allUnlocked
      ? 'These advanced capabilities are enabled on this instance.'
      : 'Upgrade your instance to enable advanced DATAGerry capabilities.';
  }

  /**
   * A feature reads as enabled only when the running edition truly grants it. An expired license still
   * carries its tier's features, so the edition gate keeps those cards in the upgrade state until renewal.
   */
  public isEnabled(feature: LicenseFeature): boolean {
    return this.allUnlocked && this.unlocked.has(feature);
  }

  /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  private buildSections(): CatalogSection[] {
    return PREMIUM_CATALOG_CATEGORIES.map((category) => ({
      key: category.key,
      label: category.label,
      items: category.features.map((feature) => this.buildItem(feature))
    }));
  }

  private buildItem(feature: LicenseFeature): CatalogItem {
    const content = PREMIUM_FEATURE_CONTENT[feature];

    return {
      feature,
      label: LICENSE_FEATURE_LABELS[feature],
      icon: content?.icon ?? FALLBACK_ICON,
      description: content?.description ?? '',
      benefits: content?.benefits ?? [],
      featured: feature === PREMIUM_FEATURED_FEATURE
    };
  }
}
