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
import { ChangeDetectionStrategy, Component, OnInit } from '@angular/core';

import { RenderFieldComponent } from '../../fields/components.fields';
import { PersonSelection, personDisplayLabel, personValueIds } from '../../../models/person-selector';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-person-simple',
    template: `<span>{{ text }}</span>`,
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class PersonSimpleComponent extends RenderFieldComponent implements OnInit {

    public text = '';

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    /** Rendered objects carry the labels; anything else falls back to the ids. */
    public ngOnInit(): void {
        const persons: PersonSelection[] | undefined = this.data?.persons;

        this.text = Array.isArray(persons)
            ? persons.map(selection => personDisplayLabel(selection)).join(', ')
            : personValueIds(this.data?.value).map(id => `#${id}`).join(', ');
    }
}
