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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { LicenseFeature } from '../../../settings/license-management/models/license.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/* -------------------------------------------------- CONSTANTS ------------------------------------------------- */

export const MODEL_DETAILS_TITLE_ID = 'model-details-title';

/* ------------------------------------------------- INTERFACES ------------------------------------------------ */

export interface BestPracticeModelCounts {
    categories: number;
    types: number;
    fields: number;
    relations: number;
}

/** One card of `GET /start_assistant/models`; the list comes in display order. */
export interface BestPracticeModelCard {
    model_id: string;
    title: string;
    badge: string;
    summary: string;
    counts: BestPracticeModelCounts;
    category_labels: string[];
    required_features: LicenseFeature[];
    missing_features: LicenseFeature[];
    applicable: boolean;
}

export interface BestPracticeTypeRef {
    name: string;
    label: string;
}

export interface BestPracticeField {
    name: string;
    label: string;
    field_type: string;
    targets: BestPracticeTypeRef[];
}

export interface BestPracticeSection {
    name: string;
    label: string;
    section_type: string;
    referenced_type: BestPracticeTypeRef | null;
    fields: BestPracticeField[];
}

export interface BestPracticeType {
    name: string;
    label: string;
    description: string | null;
    special_type: string | null;
    field_count: number;
    sections: BestPracticeSection[];
}

export interface BestPracticeCategory {
    name: string;
    label: string;
    description: string | null;
    parent: string | null;
    types: BestPracticeType[];
}

export interface BestPracticeRelation {
    name: string;
    description: string | null;
    parent_label: string | null;
    child_label: string | null;
    parent_types: BestPracticeTypeRef[];
    child_types: BestPracticeTypeRef[];
    field_count: number;
}

/** Answer of `GET /start_assistant/models/<model_id>`. */
export interface BestPracticeModelDetails extends BestPracticeModelCard {
    description: string;
    suited_for: string[];
    profiles: string[];
    categories: BestPracticeCategory[];
    uncategorized: BestPracticeType[];
    relations: BestPracticeRelation[];
}

export interface BestPracticeCountItem {
    id: keyof BestPracticeModelCounts;
    value: number;
    label: string;
}

/** A card as the import step shows it. */
export interface BestPracticeModelCardView extends BestPracticeModelCard {
    countItems: BestPracticeCountItem[];
    missingFeatureLabels: string;
}

/** A category of the details view, or the types without one. */
export interface BestPracticeTypeGroup {
    id: string;
    label: string;
    parentLabel: string;
    description: string | null;
    types: BestPracticeType[];
}
