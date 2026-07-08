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
import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { Router } from '@angular/router';

import { ImporterConfig, ImporterFile, ImportResponse } from '../../../models/import-object.models';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-import-complete',
    templateUrl: './import-complete.component.html',
    styleUrls: ['./import-complete.component.scss'],
    standalone: false
})
export class ImportCompleteComponent implements OnInit {
    @Input() public importFile: ImporterFile = {} as ImporterFile;
    @Input() public importerConfig: ImporterConfig = {} as ImporterConfig;

    @Input() public parserConfig: any = {};
    @Input() public parsedData: any = undefined;

    @Input() public importResponse: ImportResponse;
    @Input() public isImporting = false;

    @Output() startImportEmitter: EventEmitter<any>;

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */
    public constructor(private router: Router) {
        this.startImportEmitter = new EventEmitter();
    }

    public ngOnInit(): void {
        this.importResponse = undefined;
    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    public onStartImport() {
        this.startImportEmitter.emit(null);
    }


    public onListRedirect() {
        this.router.navigate(['/framework/object/type/', this.importerConfig.type_id]);
    }
}
