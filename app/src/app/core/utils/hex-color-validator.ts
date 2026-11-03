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

/** Contrast, alpha and PDF helpers all parse the full six-digit form. */
const HEX_COLOR_PATTERN = /^#[0-9a-f]{6}$/i;

/** Accepts an empty value, so pair it with `Validators.required` when a colour is mandatory. */
export function hexColorValidator(): ValidatorFn {
    return (control: AbstractControl): ValidationErrors | null => {
        const value = control.value;

        if (value === null || value === undefined || value === '') {
            return null;
        }

        return typeof value === 'string' && HEX_COLOR_PATTERN.test(value) ? null : { hexColor: true };
    };
}

/** Message for `app-color-picker`'s `errorMessage`, shown once the field has been left. */
export function hexColorErrorMessage(control: AbstractControl | null): string {
    if (!control?.invalid || !control.touched) {
        return '';
    }

    if (control.hasError('required')) {
        return 'Color is required.';
    }

    return control.hasError('hexColor') ? 'Enter a hex color such as #1e88e5.' : '';
}
