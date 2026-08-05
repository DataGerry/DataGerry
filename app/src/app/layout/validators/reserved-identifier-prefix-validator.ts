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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { AbstractControl, ValidationErrors, ValidatorFn } from '@angular/forms';

/**
 * "dg-" and "dg_" are reserved for DATAGERRY system and special-type definitions, so user-created
 * field/section identifiers must not use them.
 */
const RESERVED_IDENTIFIER_PREFIX = /^dg[-_]/i;

/**
 * Returns true when the identifier uses a reserved "dg-"/"dg_" prefix.
 * Shared by the form validator and the builder's field/section highlight checks.
 */
export function isReservedIdentifier(value: string | null | undefined): boolean {
    return typeof value === 'string' && RESERVED_IDENTIFIER_PREFIX.test(value.trim());
}

/**
 * Prevents user-created field/section identifiers from using a reserved prefix.
 *
 * @returns A ValidatorFn that flags `reservedPrefix` when the value starts with a reserved prefix.
 */
export function reservedIdentifierPrefixValidator(): ValidatorFn {
    return (control: AbstractControl): ValidationErrors | null => {
        return isReservedIdentifier(control.value) ? { reservedPrefix: true } : null;
    };
}
