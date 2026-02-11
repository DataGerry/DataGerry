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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, Input, Output, EventEmitter } from "@angular/core";


@Component({
    selector: 'app-checkbox',
    templateUrl: './checkbox.component.html',
    standalone: false
})
export class CheckboxComponent {
  @Input() label = '';
  @Input() id?: string;
  @Input() disabled = false;
  @Input() checked = false;
  @Output() checkedChange = new EventEmitter<boolean>(); 

  onInputChange(event: Event) {
    const inputEl = event.target as HTMLInputElement;
    this.checkedChange.emit(inputEl.checked);
  }
}