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
import { LicenseFeature } from '../models/license.model';
import contentFile from './premium-feature-content.json';


export interface PremiumFeatureContent {
  /** Modal heading, e.g. "Unlock Webhooks". */
  title: string;
  /** Short line naming the edition that includes the feature. */
  subtitle: string;
  /** One or two sentences describing the value of the feature. */
  description: string;
  /** Full FontAwesome class for the hero icon, e.g. "fas fa-plug". */
  icon: string;
  /** Concise selling points rendered as a checklist. */
  benefits: string[];
  /** Short scannable labels shown on the catalogue card (optional). */
  tags?: string[];
}


export const PREMIUM_FEATURE_CONTENT =
  contentFile.features as Partial<Record<LicenseFeature, PremiumFeatureContent>>;

/* -------------------------------------------------- CATALOGUE ------------------------------------------------------ */

/**
 * A labelled group of gated features, shown as a section in the catalogue. Adding a feature is a
 * data-only change: add its copy to the JSON and list its key under the right category here.
 */
export interface PremiumCatalogCategory {
  /** Stable key used for tracking. */
  key: string;
  /** Section heading shown to the user. */
  label: string;
  /** Features in display order. */
  features: LicenseFeature[];
}

/** The single capability promoted to the featured hero card. */
export const PREMIUM_FEATURED_FEATURE = LicenseFeature.Isms;

/** Catalogue taxonomy — the source of truth for sections, order, and membership. */
export const PREMIUM_CATALOG_CATEGORIES: ReadonlyArray<PremiumCatalogCategory> = [
  {
    key: 'security',
    label: 'Security & Compliance',
    features: [LicenseFeature.Isms]
  },
  {
    key: 'automation',
    label: 'Automation & Integrations',
    features: [LicenseFeature.RestApi, LicenseFeature.Automations]
  },
  {
    key: 'productivity',
    label: 'Productivity Tools',
    features: [LicenseFeature.DocumentGenerator, LicenseFeature.Ipam]
  }
];
