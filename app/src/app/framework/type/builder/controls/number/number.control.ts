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

import { ControlsCommon, ControlsContent, randomName } from '../controls.common';

class NumberContent implements ControlsContent {

    public type: string;
    public name: string;
    public label: string;
    public value: number;
    public helperText: string;
    public placeholder: string;
    public required: boolean;

    public constructor() {
        this.type = 'number';
        this.name = randomName(this.type);
        this.label = 'Number';
    }

}

export class NumberControl extends ControlsCommon {

    public name: string = 'number';
    public label: string = 'Number';
    public icon: string = 'fas fa-calculator';
    public dndType: string = 'inputs';

    public content(): NumberContent {
        return new NumberContent();
    }

}


