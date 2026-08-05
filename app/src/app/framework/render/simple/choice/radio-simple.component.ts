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

import { RenderFieldComponent } from '../../fields/components.fields';
/* ------------------------------------------------------------------------------------------------------------------ */
@Component({
    selector: 'cmdb-radio-simple',
    templateUrl: './radio-simple.component.html',
    styleUrls: ['./radio-simple.component.scss'],
    standalone: false
})
export class RadioSimpleComponent extends RenderFieldComponent {

    constructor() {
        super();
    }
}
