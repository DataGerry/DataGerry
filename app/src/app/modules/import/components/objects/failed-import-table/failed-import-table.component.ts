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
import { Component, Input, OnChanges, SimpleChanges } from '@angular/core';

import { CmdbType } from 'src/app/framework/models/cmdb-type';
import { ImportFailedEntry, ImportObjectField } from '../../../models/import-object.models';
/* ------------------------------------------------------------------------------------------------------------------ */

interface FailedValue {
    label: string;
    value: string;
}

interface FailedObjectView {
    typeLabel: string;
    publicId: number | null;
    errors: string[];
    values: FailedValue[];
}

@Component({
    selector: 'cmdb-failed-import-table',
    templateUrl: './failed-import-table.component.html',
    styleUrls: ['./failed-import-table.component.scss'],
    standalone: false
})
export class FailedImportTableComponent implements OnChanges {

    @Input() public failedImports: ImportFailedEntry[] = [];
    @Input() public typeInstance: CmdbType;

    public items: FailedObjectView[] = [];

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['failedImports'] || changes['typeInstance']) {
            this.items = (this.failedImports ?? []).map((entry) => this.toView(entry));
        }
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ------------------------------------------------ */

    private toView(entry: ImportFailedEntry): FailedObjectView {
        const failed = entry?.failed_object ?? {};

        return {
            typeLabel: failed.type_label || this.typeInstance?.label || 'Object',
            publicId: typeof failed.public_id === 'number' ? failed.public_id : null,
            errors: entry?.errors ?? [],
            values: this.collectValues(failed.fields ?? [])
        };
    }


    private collectValues(fields: ImportObjectField[]): FailedValue[] {
        return fields
            .filter((field) => this.hasValue(field?.value))
            .map((field) => ({ label: this.fieldLabel(field.name), value: this.formatValue(field.value) }));
    }


    private hasValue(value: any): boolean {
        return value !== null && value !== undefined && value !== '';
    }


    private formatValue(value: any): string {
        return typeof value === 'object' ? JSON.stringify(value) : String(value);
    }


    private fieldLabel(name: string): string {
        const match = this.typeInstance?.fields?.find((field) => field?.name === name);
        return match?.label || name;
    }
}
