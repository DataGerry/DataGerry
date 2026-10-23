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
import { ConfigurationTransferCounts } from '../../../core/models/configuration-transfer.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/* -------------------------------------------------- CONSTANTS ------------------------------------------------- */

/** Confirmation phrase the workspace reset route expects. */
export const WORKSPACE_RESET_CONFIRMATION = 'RESET';

/** Right the data model import, workspace reset and best-practice routes require. */
export const WORKSPACE_ADMIN_RIGHT = 'base.*';

/* --------------------------------------------------- TYPES --------------------------------------------------- */

export type OnboardingEdition = 'community' | 'subscription';

export type OnboardingImportSource = 'data-model' | 'best-practice' | 'empty';

export type StartAssistantDecision = 'empty_data_model';

/* ------------------------------------------------- INTERFACES ------------------------------------------------ */

export interface EditionOption {
    id: OnboardingEdition;
    icon: string;
    title: string;
    description: string;
    features: string[];
    badge: string;
}

export interface ImportOption {
    id: OnboardingImportSource;
    icon: string;
    title: string;
    description: string;
}

/** Answer of `GET /start_assistant/offer`; all false when the caller lacks the type and category add rights. `can_import` also needs `base.*`. */
export interface StartAssistantOffer {
    show: boolean;
    available: boolean;
    reset_required: boolean;
    can_import: boolean;
}

export interface OnboardingStep {
    id: string;
    title: string;
    description: string;
}

export interface DataModelCountLabel {
    id: keyof ConfigurationTransferCounts;
    label: string;
}

export interface SetupSummaryItem {
    id: string;
    icon: string;
    title: string;
    value: string;
    detail: string;
}

/* ------------------------------------------------ DISPLAY DATA ----------------------------------------------- */

export const EDITION_OPTIONS: EditionOption[] = [
    {
        id: 'community',
        icon: 'fas fa-heart',
        title: 'Community',
        description: 'Free and open source under AGPL.',
        features: ['Types, categories, objects', 'Import and export', 'Community support'],
        badge: 'Free'
    },
    {
        id: 'subscription',
        icon: 'fas fa-key',
        title: 'Subscription',
        description: 'License with Pro features and vendor support.',
        features: [
            'Everything in Community',
            'REST API, IPAM, Document Generator, Automations, ISMS (by plan)',
            'Support by becon'
        ],
        badge: 'Paid'
    }
];

export const IMPORT_OPTIONS: ImportOption[] = [
    {
        id: 'empty',
        icon: 'fas fa-file',
        title: 'Empty data model',
        description: 'Start without a data model and create your own types and categories.'
    },
    {
        id: 'best-practice',
        icon: 'fas fa-sitemap',
        title: 'Best practice model',
        description: 'Start with a ready-made data model of categories, types and relations.'
    },
    {
        id: 'data-model',
        icon: 'fas fa-file-import',
        title: 'Import data model',
        description: 'Upload a data model file exported from another DATAGERRY instance.'
    }
];

export const DATA_MODEL_COUNT_LABELS: DataModelCountLabel[] = [
    { id: 'categories', label: 'Categories' },
    { id: 'types', label: 'Types' },
    { id: 'section_templates', label: 'Section templates' },
    { id: 'relations', label: 'Relations' }
];
