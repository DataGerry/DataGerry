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
import { Component } from '@angular/core';
import { RenderFieldComponent} from '../../fields/components.fields';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    templateUrl: './password-simple.component.html',
    styleUrls: ['./password-simple.component.scss'],
    standalone: false
})
export class PasswordSimpleComponent extends RenderFieldComponent {

    public showData: boolean = false;

    constructor() {
        super();
    }


    public toggle(event: MouseEvent) {
        this.showData = !this.showData;

        event.stopPropagation();
        event.preventDefault();
    }
}
