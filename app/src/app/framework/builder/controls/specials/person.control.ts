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
import { ControlsCommon, ControlsContent, randomName } from '../controls.common';
import { PERSON_FIELD_TYPE, PersonRefKind } from '../../../models/person.model';
/* ------------------------------------------------------------------------------------------------------------------ */

class PersonContent implements ControlsContent {
    helperText: string;
    description: string;
    name: string;
    required: boolean;
    type: string;
    value: any;
    label: string;
    person_ref_kind: PersonRefKind;
    multiple: boolean;

    public constructor() {
        this.type = PERSON_FIELD_TYPE;
        this.name = randomName(this.type);
        this.label = 'Person';
        this.person_ref_kind = PersonRefKind.BOTH;
        this.multiple = false;
    }
}


/** The "Person / Person group selector": selects objects of the PERSON and/or PERSON_GROUP special type. */
export class PersonControl extends ControlsCommon {
    public name: string = PERSON_FIELD_TYPE;
    public label: string = 'Person / Person group';
    public icon: string = 'fas fa-user-tag';
    public dndType: string = PERSON_FIELD_TYPE;

    public content(): PersonContent {
        return new PersonContent();
    }
}
