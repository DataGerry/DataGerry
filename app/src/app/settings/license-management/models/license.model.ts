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

/**
 * Individually gated features a license can unlock (anything not listed belongs to Community).
 */
export enum LicenseFeature {
  RestApi = 'rest_api',
  Ipam = 'ipam',
  Isms = 'isms',
  DocumentGenerator = 'document_generator',
  Automations = 'automations'
}

/** UI-level edition resolved from the license state (on-premise only). */
export enum LicenseEdition {
  Community = 'community',
  SelfHosted = 'self_hosted',
  Expired = 'expired'
}

export enum LicenseTier {
  Free = 'free',
  Core = 'core',
  Business = 'business',
  Corporate = 'corporate'
}

/** Human-readable tier names shown on the license card. */
export const LICENSE_TIER_LABELS: Record<LicenseTier, string> = {
  [LicenseTier.Free]: 'Community',
  [LicenseTier.Core]: 'Core',
  [LicenseTier.Business]: 'Business',
  [LicenseTier.Corporate]: 'Corporate'
};

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
  features: LicenseFeature[];
}

/**
 * Raw wire payload of `GET /rest/license/current` and the activate endpoint.
 */
export interface CurrentLicenseResponse {
  hmac: string;
  startDate: number;
  endDate: number;
  subId: string;
  licenseId: string;
  type: string;
  features: LicenseFeature[];
  operationUsage?: number;
  duration?: number;
  is_active: boolean;
  status: LicenseVerificationStatus | null;
}

/** Domain model the UI consumes: the verification flags plus the entitlement grouped together. */
export interface CurrentLicense {
  is_active: boolean;
  status: LicenseVerificationStatus | null;
  entitlement: LicenseEntitlement;
}

/* ------------------------------------------------ DISPLAY DATA ----------------------------------------------- */

/** Human-readable feature names. */
export const LICENSE_FEATURE_LABELS: Record<LicenseFeature, string> = {
  [LicenseFeature.RestApi]: 'REST API',
  [LicenseFeature.Ipam]: 'IPAM',
  [LicenseFeature.Isms]: 'ISMS',
  [LicenseFeature.DocumentGenerator]: 'Document Generator',
  [LicenseFeature.Automations]: 'Automations'
};

/**
 * Short headlines paired with {@link LICENSE_STATUS_MESSAGES} when a stored license fails
 * verification. `Valid` is never surfaced as a warning.
 */
export const LICENSE_STATUS_TITLES: Record<LicenseVerificationStatus, string> = {
  [LicenseVerificationStatus.Valid]: '',
  [LicenseVerificationStatus.DecryptFailed]: 'License could not be verified',
  [LicenseVerificationStatus.SchemaInvalid]: 'License could not be verified',
  [LicenseVerificationStatus.NoActivationRequest]: 'License not recognized on this machine',
  [LicenseVerificationStatus.BindingMismatch]: 'License not recognized on this machine',
  [LicenseVerificationStatus.NotYetValid]: 'License not active yet',
  [LicenseVerificationStatus.Expired]: 'License expired'
};

/**
 * Explanations shown when a stored license fails verification (degrading the install to Community).
 * Each pairs with the matching {@link LICENSE_STATUS_TITLES} headline; `Valid` is never surfaced.
 */
export const LICENSE_STATUS_MESSAGES: Record<LicenseVerificationStatus, string> = {
  [LicenseVerificationStatus.Valid]: '',
  [LicenseVerificationStatus.DecryptFailed]:
    'The stored license is corrupted or was tampered with and has been disabled. Import a valid license below to restore the Self-Hosted Edition.',
  [LicenseVerificationStatus.SchemaInvalid]:
    'The stored license is malformed and has been disabled. Import a valid license below to restore the Self-Hosted Edition.',
  [LicenseVerificationStatus.NoActivationRequest]:
    'No matching activation request was found on this machine. Generate a new activation request below and re-issue the license.',
  [LicenseVerificationStatus.BindingMismatch]:
    'This license is bound to a different machine and cannot be used here. Generate a new activation request below and re-issue the license.',
  [LicenseVerificationStatus.NotYetValid]:
    'The stored license is not valid yet. Check the start date on the license.',
  [LicenseVerificationStatus.Expired]:
    'Your Self-Hosted features have been disabled. Renew your license and import the new file below to restore them.'
};
