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
import { Observable, from } from 'rxjs';

import {
  COMMUNITY_TIER,
  CurrentLicense,
  LicenseEdition,
  LicenseFeature,
  LicenseVerificationStatus,
  SELF_HOSTED_FEATURES
} from '../models/license.model';

/** Milliseconds in a day, used to derive the remaining validity period. */
const MS_PER_DAY = 86_400_000;

/**
 * Resolves the UI edition from the current license (on-premise only).
 *
 * An active non-free license is Self-Hosted, an expired license is flagged as such, and everything
 * else falls back to Community.
 */
export function resolveEdition(license: CurrentLicense | null): LicenseEdition {
  if (!license) {
    return LicenseEdition.Community;
  }

  if (license.is_active && license.entitlement.type !== COMMUNITY_TIER) {
    return LicenseEdition.SelfHosted;
  }

  if (license.status === LicenseVerificationStatus.Expired) {
    return LicenseEdition.Expired;
  }

  return LicenseEdition.Community;
}

/**
 * Days remaining until the license expires.
 *
 * Returns `null` for a perpetual license (`endDate === 0`) and a negative number when the license
 * has already lapsed.
 */
export function remainingDays(endDate: number, now: number): number | null {
  if (!endDate) {
    return null;
  }

  return Math.ceil((endDate - now) / MS_PER_DAY);
}

/** Features unlocked by the entitlement tier: all features for Self-Hosted, none for Community. */
export function tierFeatures(type: string): LicenseFeature[] {
  return type === COMMUNITY_TIER ? [] : SELF_HOSTED_FEATURES;
}

/**
 * Extracts the download filename from a `Content-Disposition` header.
 *
 * Prefers the RFC 5987 `filename*` form, falling back to the plain `filename`. Returns `null` when
 * no filename is present (e.g. the header is not exposed across origins).
 */
export function parseContentDispositionFilename(header: string | null): string | null {
  if (!header) {
    return null;
  }

  const utf8Match = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(header);
  if (utf8Match?.[1]) {
    return decodeURIComponent(utf8Match[1].replace(/"/g, '').trim());
  }

  const asciiMatch = /filename="?([^";]+)"?/i.exec(header);
  return asciiMatch?.[1]?.trim() ?? null;
}

/** Reads a selected license file as UTF-8 text (the Base64 blob expected by the activate endpoint). */
export function readLicenseFile(file: File): Observable<string> {
  return from(file.text());
}
