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
import { Component, EventEmitter, Input, OnChanges, OnDestroy, OnInit, Output, SimpleChanges } from '@angular/core';
import { FormControl, FormGroup } from '@angular/forms';

import { Subscription } from 'rxjs';

import { ImportTypeAction, ImportTypeEntry } from '../../../models/import-type.models';
import { TypePreviewRow, buildTypePreviewRows, filterTypePreviewRows } from './type-preview.row';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-type-preview',
    templateUrl: './type-preview.component.html',
    styleUrls: ['./type-preview.component.scss'],
    standalone: false
})
export class TypePreviewComponent implements OnInit, OnChanges, OnDestroy {

    @Input() public types: ImportTypeEntry[] = [];
    @Input() public action: ImportTypeAction = 'create';

    @Output() public actionChange = new EventEmitter<ImportTypeAction>();

    /** Index of the entry the user removed from the upload. */
    @Output() public typeRemoved = new EventEmitter<number>();

    public readonly previewForm = new FormGroup({
        action: new FormControl<ImportTypeAction>('create', { nonNullable: true }),
        search: new FormControl('', { nonNullable: true })
    });

    public rows: TypePreviewRow[] = [];
    public visibleRows: TypePreviewRow[] = [];

    private readonly subscriptions = new Subscription();

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    public ngOnInit(): void {
        this.subscriptions.add(this.actionControl.valueChanges.subscribe((action) => {
            this.actionChange.emit(action);
        }));

        this.subscriptions.add(this.searchControl.valueChanges.subscribe(() => this.applySearch()));
    }


    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['types']) {
            this.rows = buildTypePreviewRows(this.types);
            this.applySearch();
        }

        if (changes['action'] && this.actionControl.value !== this.action) {
            this.actionControl.setValue(this.action, { emitEvent: false });
        }
    }


    public ngOnDestroy(): void {
        this.subscriptions.unsubscribe();
    }

/* ------------------------------------------------- GETTER / SETTER ------------------------------------------------ */

    public get actionControl(): FormControl<ImportTypeAction> {
        return this.previewForm.controls.action;
    }


    public get searchControl(): FormControl<string> {
        return this.previewForm.controls.search;
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onRemoveType(row: TypePreviewRow): void {
        this.typeRemoved.emit(row.index);
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private applySearch(): void {
        this.visibleRows = filterTypePreviewRows(this.rows, this.searchControl.value);
    }
}
