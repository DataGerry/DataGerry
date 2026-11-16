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
import { ValidatorFn, AbstractControl, ValidationErrors } from "@angular/forms";

export function uniqueCalculationBasisValidator(existingValues: number[], currentValue?: number): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    if (!control.value) return null;
    const valueFloat = parseFloat(control.value);
    if (isNaN(valueFloat)) return null;
    // Allow unchanged value in edit mode.
    if (currentValue !== undefined && valueFloat === currentValue) {
      return null;
    }
    return existingValues.includes(valueFloat) ? { duplicateCalculationBasis: true } : null;
  };
}


export function numericOrDecimalValidator(): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    const value = control.value;

    if (value === null || value === '') {
      return null;
    }

    const isValid = !isNaN(value) && /^-?\d+(\.\d+)?$/.test(value.toString());
    return isValid ? null : { invalidNumber: true };
  };
}



export function nonZeroValidator(): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    const value = parseFloat(control.value);
    if (!isNaN(value) && value === 0) {
      return { zeroNotAllowed: true };
    }
    return null;
  };
}


/** Assessment dates arrive as a datepicker struct, an ISO string or a Mongo `$date`; renders them as YYYY-MM-DD. */
export function formatIsmsDate(value: unknown): string {
  if (!value) {
    return '';
  }

  if (typeof value === 'object' && 'year' in value && 'month' in value && 'day' in value) {
    const { year, month, day } = value as { year: number; month: number; day: number };
    return `${year}-${`${month}`.padStart(2, '0')}-${`${day}`.padStart(2, '0')}`;
  }

  const raw = typeof value === 'object' && '$date' in value ? (value as { $date: unknown }).$date : value;

  if (typeof raw === 'string' && /^\d{4}-\d{2}-\d{2}/.test(raw)) {
    return raw.slice(0, 10);
  }

  const date = new Date(raw as string | number);
  return isNaN(date.getTime()) ? '' : date.toISOString().slice(0, 10);
}
