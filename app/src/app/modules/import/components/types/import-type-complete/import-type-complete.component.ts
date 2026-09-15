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
import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges } from '@angular/core';
import { Router } from '@angular/router';

import { ImportTypeAction, ImportTypeResponse } from '../../../models/import-type.models';
/* ------------------------------------------------------------------------------------------------------------------ */

type ImportOutcome = 'success' | 'partial' | 'failed' | 'empty';

@Component({
    selector: 'cmdb-import-type-complete',
    templateUrl: './import-type-complete.component.html',
    styleUrls: ['./import-type-complete.component.scss'],
    standalone: false
})
export class ImportTypeCompleteComponent implements OnChanges {

    @Input() public fileName = '';
    @Input() public typeCount = 0;
    @Input() public action: ImportTypeAction = 'create';
    @Input() public importResponse: ImportTypeResponse;
    @Input() public isImporting = false;

    @Output() public startImportEmitter = new EventEmitter<void>();

    // Derived view state for the result banner and the failed-types section.
    public outcome: ImportOutcome = 'empty';
    public importedCount = 0;
    public failedCount = 0;

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    public constructor(private readonly router: Router) {}


    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['importResponse']) {
            this.buildImportResult();
        }
    }

/* ------------------------------------------------- GETTER / SETTER ------------------------------------------------ */

    public get actionLabel(): string {
        return this.action === 'update' ? 'Update existing types' : 'Create new types';
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onStartImport(): void {
        this.startImportEmitter.emit();
    }


    public onTypeListRedirect(): void {
        this.router.navigate(['/framework/type/']);
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private buildImportResult(): void {
        this.importedCount = this.importResponse?.success_imports ?? 0;
        this.failedCount = this.importResponse?.failed_imports?.length ?? 0;
        this.outcome = this.resolveOutcome(this.importedCount, this.failedCount);
    }


    private resolveOutcome(imported: number, failed: number): ImportOutcome {
        if (imported === 0 && failed === 0) {
            return 'empty';
        }

        if (failed === 0) {
            return 'success';
        }

        return imported === 0 ? 'failed' : 'partial';
    }
}
