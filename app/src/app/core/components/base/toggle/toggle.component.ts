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

import { Component, Input } from '@angular/core';
import { ControlContainer, FormGroupDirective } from '@angular/forms';

@Component({
    selector: 'app-toggle',
    templateUrl: './toggle.component.html',
    styleUrls: ['./toggle.component.scss'],
    viewProviders: [{ provide: ControlContainer, useExisting: FormGroupDirective }],
    standalone: false
})
export class ToggleComponent {
    @Input() public label = '';
<<<<<<< HEAD
    @Input() public formControlName = '';
=======
    @Input() public controlName = '';
>>>>>>> origin/version-3.2
    @Input() public id = '';
    @Input() public ariaLabel = '';


    public get resolvedId(): string {
<<<<<<< HEAD
        return this.id || this.formControlName || 'app-toggle-input';
=======
        return this.id || this.controlName || 'app-toggle-input';
>>>>>>> origin/version-3.2
    }


    public get resolvedAriaLabel(): string {
        return this.ariaLabel || this.label;
    }
}
