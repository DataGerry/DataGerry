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
import { ChangeDetectorRef, Component, OnDestroy, OnInit, inject } from '@angular/core';

import { ReplaySubject, takeUntil } from 'rxjs';

import { RenderFieldComponent } from '../../fields/components.fields';
import { PersonRelationsService } from '../../../services/person-relations.service';
import { PersonSelection, personSelectionKey, personSelectionsOf } from '../../../models/person.model';
/* ------------------------------------------------------------------------------------------------------------------ */

interface PersonSimpleEntry extends PersonSelection {
    key: string;
    label: string;
    missing: boolean;
}

/**
 * Table cell of a person field: the selected persons / groups as links to their objects. All cells of a
 * table share one candidate request through PersonRelationsService.
 */
@Component({
    selector: 'cmdb-person-simple',
    templateUrl: './person-simple.component.html',
    styleUrls: ['./person-simple.component.scss'],
    standalone: false
})
export class PersonSimpleComponent extends RenderFieldComponent implements OnInit, OnDestroy {

    private readonly personRelationsService = inject(PersonRelationsService);
    private readonly cd = inject(ChangeDetectorRef);
    private readonly unsubscribe = new ReplaySubject<void>();

    public entries: Array<PersonSimpleEntry> = [];

    public ngOnInit(): void {
        const selections = personSelectionsOf(this.data?.value);
        this.entries = selections.map(selection => ({
            ...selection,
            key: personSelectionKey(selection),
            label: `#${ selection.id }`,
            missing: true
        }));

        if (!selections.length) {
            return;
        }

        this.personRelationsService.resolveSelections(selections)
            .pipe(takeUntil(this.unsubscribe))
            .subscribe({
                next: (byKey) => {
                    this.entries = this.entries.map(entry => {
                        const candidate = byKey.get(entry.key);
                        return candidate ? { ...entry, label: candidate.label, missing: false } : entry;
                    });
                    this.cd.markForCheck();
                },
                error: () => undefined
            });
    }


    public ngOnDestroy(): void {
        this.unsubscribe.next();
        this.unsubscribe.complete();
    }


    public iconOf(entry: PersonSelection): string {
        return entry.ref_type === 'PERSON_GROUP' ? 'fas fa-users' : 'fas fa-user';
    }
}
