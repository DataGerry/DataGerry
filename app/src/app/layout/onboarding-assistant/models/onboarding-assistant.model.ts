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
/* ------------------------------------------------------------------------------------------------------------------ */

/* -------------------------------------------------- CONSTANTS ------------------------------------------------- */

/** Confirmation phrase the workspace reset route expects. */
export const WORKSPACE_RESET_CONFIRMATION = 'RESET';

/* --------------------------------------------------- TYPES --------------------------------------------------- */

export type OnboardingEdition = 'community' | 'subscription';

export type OnboardingImportSource = 'data-model' | 'empty';

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

/** Answer of `GET /start_assistant/offer`; all false when the caller lacks the type and category add rights. */
export interface StartAssistantOffer {
    show: boolean;
    available: boolean;
    reset_required: boolean;
}

export interface OnboardingStep {
    id: string;
    title: string;
    description: string;
}

export interface SetupSummaryItem {
    id: string;
    icon: string;
    title: string;
    value: string;
    detail: string;
}
