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
import { ControlsCommon, StructureContent, randomName } from './controls.common';
/* ------------------------------------------------------------------------------------------------------------------ */

export class MultiSectionContent implements StructureContent {
    label: string;
    name: string;
    fields: Array<any> = [];
    type: string = 'multi-data-section';
    hidden_fields: Array<any> = [];

    constructor() {
        this.type = 'multi-data-section';
        this.name = randomName(this.type);
        this.label = 'Multi Data Section';
    }

}


export class MultiSectionControl extends ControlsCommon {
    name = 'multi-data-section';
    label = 'Multi Data Section';
    icon = 'fas fa-list-ol';
    dndType: string = 'sections';

    public content(): MultiSectionContent {
        return new MultiSectionContent();
    }

}