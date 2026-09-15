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
import { Component, EventEmitter, Input, OnChanges, OnInit, Output, SimpleChanges } from '@angular/core';
import { Router } from '@angular/router';

import { CmdbType } from 'src/app/framework/models/cmdb-type';
import { ImporterConfig, ImporterFile, ImportResponse } from '../../../models/import-object.models';
/* ------------------------------------------------------------------------------------------------------------------ */

type ImportOutcome = 'success' | 'partial' | 'failed' | 'empty';

@Component({
    selector: 'cmdb-import-complete',
    templateUrl: './import-complete.component.html',
    styleUrls: ['./import-complete.component.scss'],
    standalone: false
})
export class ImportCompleteComponent implements OnInit, OnChanges {
    @Input() public importFile: ImporterFile = {} as ImporterFile;
    @Input() public importerConfig: ImporterConfig = {} as ImporterConfig;
    @Input() public typeInstance: CmdbType;

    @Input() public parserConfig: any = {};
    @Input() public parsedData: any = undefined;

    @Input() public importResponse: ImportResponse;
    @Input() public isImporting = false;

    @Output() startImportEmitter: EventEmitter<any>;

    // Derived view state for the import result banner and failed-objects section.
    public outcome: ImportOutcome = 'empty';
    public importedCount = 0;
    public failedCount = 0;

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */
    public constructor(private router: Router) {
        this.startImportEmitter = new EventEmitter();
    }

    public ngOnInit(): void {
        this.importResponse = undefined;
    }


    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['importResponse']) {
            this.buildImportResult();
        }
    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    public onStartImport() {
        this.startImportEmitter.emit(null);
    }


    public onListRedirect() {
        this.router.navigate(['/framework/object/type/', this.importerConfig.type_id]);
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ------------------------------------------------ */

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
