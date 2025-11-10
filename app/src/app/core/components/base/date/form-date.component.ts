/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, Input } from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';

@Component({
    selector: 'app-form-date',
    templateUrl: './form-date.component.html',
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: FormDateComponent,
            multi: true
        }
    ],
    standalone: false
})
export class FormDateComponent implements ControlValueAccessor {
  @Input() disabled = false;
  @Input() defaultToCurrent: boolean = false;

  private internalValue: any;
  public displayedValue = '';

  onChange = (_: any) => { };
  onTouch = () => { };

  // writeValue(value: any): void {
  //   this.internalValue = value;
  //   this.displayedValue = this.dateObjToString(value);
  // }

  writeValue(value: any): void {
    if (value == null && this.defaultToCurrent) {
      const now = new Date();
      const defaultDate = {
        year: now.getFullYear(),
        month: now.getMonth() + 1,
        day: now.getDate()
      };
      this.internalValue = defaultDate;
      this.displayedValue = this.dateObjToString(defaultDate);
      // Propagate the default value asynchronously
      setTimeout(() => {
        this.onChange(defaultDate);
      }, 0);
    } else {
      this.internalValue = value;
      this.displayedValue = this.dateObjToString(value);
    }
  }

  registerOnChange(fn: any): void { this.onChange = fn; }
  registerOnTouched(fn: any): void { this.onTouch = fn; }
  setDisabledState(isDisabled: boolean): void { this.disabled = isDisabled; }

  onInputChange(event: any) {
    const val = event.target.value; // 'YYYY-MM-DD'
    if (!val) {
      this.onChange(null);
      return;
    }
    const parts = val.split('-');
    if (parts.length === 3) {
      const year = +parts[0];
      const month = +parts[1];
      const day = +parts[2];
      this.onChange({ year, month, day });
    } else {
      this.onChange(null);
    }
  }

  private dateObjToString(value: any): string {
    if (value && value.year && value.month && value.day) {
      const mm = String(value.month).padStart(2, '0');
      const dd = String(value.day).padStart(2, '0');
      return `${value.year}-${mm}-${dd}`;
    }
    return '';
  }
}
