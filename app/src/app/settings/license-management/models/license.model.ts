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


/* -------------------------------------------------- CONSTANTS ------------------------------------------------- */

export const COMMUNITY_TIER = 'free';

/* --------------------------------------------------- ENUMS --------------------------------------------------- */

/** Outcome of the backend license verification chain (`null` when no license is stored). */
export enum LicenseVerificationStatus {
  Valid = 'valid',
  DecryptFailed = 'decrypt_failed',
  SchemaInvalid = 'schema_invalid',
  NoActivationRequest = 'no_activation_request',
  BindingMismatch = 'binding_mismatch',
  NotYetValid = 'not_yet_valid',
  Expired = 'expired'
}

/** Individually gated features a tier can unlock (anything not listed belongs to Community). */
export enum LicenseFeature {
  ApiAccess = 'api_access',
  Webhooks = 'webhooks',
  Ipam = 'ipam',
  Isms = 'isms',
  AiDocGeneration = 'ai_doc_generation',
  Automations = 'automations'
}

/** UI-level edition resolved from the license state (on-premise only). */
export enum LicenseEdition {
  Community = 'community',
  SelfHosted = 'self_hosted',
  Expired = 'expired'
}

/* ------------------------------------------------- INTERFACES ------------------------------------------------ */

/** Decrypted license payload (epoch-millisecond dates; `endDate === 0` means no expiry). */
export interface LicenseEntitlement {
  hmac: string;
  startDate: number;
  endDate: number;
  subId: string;
  licenseId: string;
  operationUsage: number;
  duration: number;
  type: string;
}

/** Payload of `GET /rest/license/current`. */
export interface CurrentLicense {
  is_active: boolean;
  status: LicenseVerificationStatus | null;
  entitlement: LicenseEntitlement;
}

/* ------------------------------------------------ DISPLAY DATA ----------------------------------------------- */

/** Every gated feature unlocked by the Self-Hosted edition (Community unlocks none). */
export const SELF_HOSTED_FEATURES: LicenseFeature[] = [
  LicenseFeature.ApiAccess,
  LicenseFeature.Webhooks,
  LicenseFeature.Ipam,
  LicenseFeature.Isms,
  LicenseFeature.AiDocGeneration,
  LicenseFeature.Automations
];

/** Human-readable feature names. */
export const LICENSE_FEATURE_LABELS: Record<LicenseFeature, string> = {
  [LicenseFeature.ApiAccess]: 'External API access',
  [LicenseFeature.Webhooks]: 'Webhooks',
  [LicenseFeature.Ipam]: 'IPAM',
  [LicenseFeature.Isms]: 'ISMS',
  [LicenseFeature.AiDocGeneration]: 'AI documentation generation',
  [LicenseFeature.Automations]: 'Automations'
};

/**
 * Explanations shown when a stored license fails verification (degrading the install to Community).
 * `Valid` is never surfaced as a warning.
 */
export const LICENSE_STATUS_MESSAGES: Record<LicenseVerificationStatus, string> = {
  [LicenseVerificationStatus.Valid]: '',
  [LicenseVerificationStatus.DecryptFailed]:
    'The stored license could not be decrypted. Please import a valid license file.',
  [LicenseVerificationStatus.SchemaInvalid]:
    'The stored license is malformed. Please import a valid license file.',
  [LicenseVerificationStatus.NoActivationRequest]:
    'No matching activation request was found on this machine. Generate a new activation request and re-issue the license.',
  [LicenseVerificationStatus.BindingMismatch]:
    'The stored license is bound to a different machine. Generate a new activation request and re-issue the license.',
  [LicenseVerificationStatus.NotYetValid]:
    'The stored license is not valid yet. Check the start date on the license.',
  [LicenseVerificationStatus.Expired]:
    'The license has expired. Import a renewed license file to restore the Self-Hosted Edition.'
};
