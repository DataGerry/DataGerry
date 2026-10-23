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

/* -------------------------------------------------- CONSTANTS ------------------------------------------------- */

export const EMPTY_LICENSE_FILE_MESSAGE = 'The selected license file is empty.';
export const LICENSE_IMPORT_FAILED_MESSAGE = 'The license could not be imported.';

/* --------------------------------------------------- ENUMS --------------------------------------------------- */

/** Sub-steps of the license activation; the values are their display numbers. */
export enum ActivationPhase {
    Request = 1,
    Portal = 2,
    Import = 3
}

/* --------------------------------------------------- TYPES --------------------------------------------------- */

export type OnboardingLicenseStatus = 'none' | 'active' | 'skipped';

export type ActivationSubStepState = 'done' | 'current' | 'idle';

/* ------------------------------------------------- INTERFACES ------------------------------------------------ */

export interface ActivationRequestFile {
    content: string;
    size: number;
    createdAt: number;
}

export interface ActivationSubStep {
    phase: ActivationPhase;
    title: string;
    state: ActivationSubStepState;
    isOpen: boolean;
    isCollapsible: boolean;
    hasFramedPanel: boolean;
    summary: string;
}

/* ------------------------------------------------ DISPLAY DATA ----------------------------------------------- */

export const ACTIVATION_SUB_STEP_ORDER = [ActivationPhase.Request, ActivationPhase.Portal, ActivationPhase.Import];

export const ACTIVATION_SUB_STEP_TITLES: Record<ActivationPhase, string> = {
    [ActivationPhase.Request]: 'Create activation request',
    [ActivationPhase.Portal]: 'Redeem in the Service Portal',
    [ActivationPhase.Import]: 'Import license file'
};
