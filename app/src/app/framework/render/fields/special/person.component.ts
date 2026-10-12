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
import { Component, OnDestroy, OnInit, inject } from '@angular/core';

import { ReplaySubject, takeUntil } from 'rxjs';

import { RenderFieldComponent } from '../components.fields';
import { CmdbMode } from '../../../modes.enum';
import { PersonRelationsService } from '../../../services/person-relations.service';
import {
    PersonCandidate,
    PersonFieldValue,
    PersonRefKind,
    PersonSelection,
    personSelectionKey,
    personSelectionsOf
} from '../../../models/person.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** A candidate as the select lists it: keyed, so the select can bind a plain string. */
export interface PersonSelectItem extends PersonCandidate {
    key: string;
    /** Heading of the option group the item is listed under. */
    groupLabel: string;
    /** The stored selection points at an object that no longer exists (or is not selectable). */
    missing?: boolean;
}

/**
 * The "Person / Person group selector" field. Selects objects of the PERSON and/or PERSON_GROUP special
 * type (the field's `person_ref_kind`), one or several (`multiple`). The form control holds the stored
 * shape: one `{ref_type, id}` pair or null, or a list of pairs.
 */
@Component({
    templateUrl: './person.component.html',
    styleUrls: ['./person.component.scss'],
    standalone: false
})
export class PersonComponent extends RenderFieldComponent implements OnInit, OnDestroy {

    private readonly personRelationsService = inject(PersonRelationsService);
    private readonly unsubscribe = new ReplaySubject<void>();

    public items: Array<PersonSelectItem> = [];
    public selectedKeys: Array<string> | string | null = null;
    public viewSelections: Array<PersonSelectItem> = [];
    public loading: boolean = false;

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        const selections = personSelectionsOf(this.controller?.value ?? this.data?.value);

        if (this.mode === CmdbMode.View) {
            this.resolveView(selections);
            return;
        }

        this.selectedKeys = this.isMultiple
            ? selections.map(personSelectionKey)
            : (selections.length ? personSelectionKey(selections[0]) : null);

        this.loadCandidates(selections);
    }


    public ngOnDestroy(): void {
        this.unsubscribe.next();
        this.unsubscribe.complete();
    }

    /* ---------------------------------------------------- GETTERS ----------------------------------------------------- */

    public get isMultiple(): boolean {
        return this.data?.multiple === true;
    }


    public get refKind(): PersonRefKind {
        return this.data?.person_ref_kind ?? PersonRefKind.BOTH;
    }


    public get placeholder(): string {
        switch (this.refKind) {
            case PersonRefKind.PERSON: return this.isMultiple ? 'Select persons' : 'Select a person';
            case PersonRefKind.PERSON_GROUP: return this.isMultiple ? 'Select person groups' : 'Select a person group';
            default: return this.isMultiple ? 'Select persons or person groups' : 'Select a person or person group';
        }
    }

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** Writes the picked keys back as the stored value shape. */
    public onSelectionChange(keys: Array<string> | string | null): void {
        const byKey = new Map(this.items.map(item => [item.key, item]));
        const toSelection = (key: string): PersonSelection | null => {
            const item = byKey.get(key);
            return item ? { ref_type: item.ref_type, id: item.id } : null;
        };

        let value: PersonFieldValue;

        if (this.isMultiple) {
            value = (Array.isArray(keys) ? keys : []).map(toSelection).filter((selection): selection is PersonSelection => !!selection);
        } else {
            value = typeof keys === 'string' ? toSelection(keys) : null;
        }

        this.controller.setValue(value);
        this.controller.markAsDirty();
        this.controller.markAsTouched();
    }


    public searchItem = (term: string, item: PersonSelectItem): boolean =>
        `${ item.label } #${ item.id }`.toLocaleLowerCase().includes((term ?? '').toLocaleLowerCase());


    public iconOf(item: PersonSelection): string {
        return item?.ref_type === 'PERSON_GROUP' ? 'fas fa-users' : 'fas fa-user';
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private loadCandidates(selections: Array<PersonSelection>): void {
        this.loading = true;

        // An edit form always reads a fresh list, so a person created a moment ago is offered
        this.personRelationsService.getCandidates(this.refKind, true)
            .pipe(takeUntil(this.unsubscribe))
            .subscribe({
                next: (candidates) => {
                    this.loading = false;
                    this.items = this.withMissingSelections(
                        candidates.map(candidate => this.toItem(candidate)),
                        selections
                    );
                },
                error: (error) => {
                    this.loading = false;
                    this.items = this.withMissingSelections([], selections);
                    this.toast?.error(error?.error?.message ?? 'Persons could not be loaded.');
                }
            });
    }


    /** A stored selection the list no longer offers is kept visible rather than silently dropped. */
    private withMissingSelections(items: Array<PersonSelectItem>, selections: Array<PersonSelection>): Array<PersonSelectItem> {
        const known = new Set(items.map(item => item.key));
        const missing = selections
            .filter(selection => !known.has(personSelectionKey(selection)))
            .map(selection => this.missingItem(selection));

        return [...items, ...missing];
    }


    private resolveView(selections: Array<PersonSelection>): void {
        this.viewSelections = selections.map(selection => this.missingItem(selection));

        if (!selections.length) {
            return;
        }

        this.loading = true;
        this.personRelationsService.resolveSelections(selections)
            .pipe(takeUntil(this.unsubscribe))
            .subscribe({
                next: (byKey) => {
                    this.loading = false;
                    this.viewSelections = selections.map(selection => {
                        const candidate = byKey.get(personSelectionKey(selection));
                        return candidate ? this.toItem(candidate) : this.missingItem(selection);
                    });
                },
                error: () => this.loading = false
            });
    }


    private toItem(candidate: PersonCandidate): PersonSelectItem {
        return {
            ...candidate,
            key: personSelectionKey(candidate),
            groupLabel: candidate.ref_type === 'PERSON_GROUP' ? 'Person groups' : 'Persons'
        };
    }


    private missingItem(selection: PersonSelection): PersonSelectItem {
        return {
            ...this.toItem({ ref_type: selection.ref_type, id: selection.id, label: `#${ selection.id }`, type_id: null }),
            missing: true
        };
    }
}
