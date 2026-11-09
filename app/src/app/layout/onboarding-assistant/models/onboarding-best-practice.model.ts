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
import { ConfigurationTransferCounts } from '../../../core/models/configuration-transfer.model';
import { StartAssistantDecisionRecord } from './onboarding-assistant.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/* -------------------------------------------------- CONSTANTS ------------------------------------------------- */

export const MODEL_DETAILS_TITLE_ID = 'model-details-title';

export const MODEL_GOALS_TITLE_ID = 'model-goals-title';

/** The DataModels README's "You want / Select" combinations; a model id is the model's file name. */
export const BEST_PRACTICE_GOALS: BestPracticeGoal[] = [
    {
        id: 'it-cmdb-software',
        title: 'IT CMDB with software assets',
        summary: 'IT CMDB plus software asset management',
        icon: 'fas fa-layer-group',
        modelIds: ['workplace_management', 'data_center', 'network_infrastructure', 'software_licenses']
    },
    {
        id: 'ai-governance',
        title: 'AI governance',
        summary: 'AI inventory with data protection and providers',
        icon: 'fas fa-microchip',
        modelIds: ['ai_systems', 'data_protection', 'supplier_management']
    },
    {
        id: 'software-manufacturer',
        title: 'Software manufacturer (CRA)',
        summary: 'EU Cyber Resilience Act: SBOMs, vulnerabilities, suppliers',
        icon: 'fas fa-cube',
        modelIds: ['sbom_supply_chain', 'supplier_management']
    },
    {
        id: 'manufacturing',
        title: 'Manufacturing',
        summary: 'OT plus the plant buildings',
        icon: 'fas fa-industry',
        modelIds: ['production_ot', 'facility_management']
    },
    {
        id: 'hospital',
        title: 'Hospital',
        summary: 'Medical devices and the IT they run on',
        icon: 'fas fa-heart-pulse',
        modelIds: ['medical_technology', 'network_infrastructure']
    }
];

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

/** Answer of `POST /start_assistant/models/preview`; `merged` holds per component the names created once. */
export interface BestPracticeSelectionPreview {
    model_ids: string[];
    counts: BestPracticeModelCounts;
    category_labels: string[];
    required_features: LicenseFeature[];
    missing_features: LicenseFeature[];
    conflicts: string[];
    merged: Partial<Record<'section_templates' | 'types' | 'categories' | 'relations', string[]>>;
    problems: string[];
    reset_blockers: string[];
    applicable: boolean;
}

export interface BestPracticeGoal {
    id: string;
    title: string;
    summary: string;
    icon: string;
    modelIds: string[];
}

/** A goal with the cards the installation offers; ids without a card are left out. */
export interface BestPracticeGoalView extends BestPracticeGoal {
    models: BestPracticeModelCardView[];
    applicableModelIds: string[];
    lockedModels: BestPracticeModelCardView[];
}

/** Answer of `POST /start_assistant/models`. */
export interface BestPracticeApplyResult {
    model_ids: string[];
    imported: ConfigurationTransferCounts;
    decision: StartAssistantDecisionRecord;
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
