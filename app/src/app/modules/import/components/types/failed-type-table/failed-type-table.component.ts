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

import { ImportTypeEntry, ImportTypeFailedEntry } from '../../../models/import-type.models';
/* ------------------------------------------------------------------------------------------------------------------ */

interface FailedTypeMeta {
    label: string;
    value: string;
}

interface FailedTypeView {
    label: string;
    name: string;
    publicId: number | null;
    errors: string[];
    meta: FailedTypeMeta[];
}

@Component({
    selector: 'cmdb-failed-type-table',
    templateUrl: './failed-type-table.component.html',
    styleUrls: ['./failed-type-table.component.scss'],
    standalone: false
})
export class FailedTypeTableComponent implements OnChanges {

    @Input() public failedImports: ImportTypeFailedEntry[] = [];

    public items: FailedTypeView[] = [];

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['failedImports']) {
            this.items = (this.failedImports ?? []).map((entry) => this.toView(entry));
        }
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private toView(entry: ImportTypeFailedEntry): FailedTypeView {
        // A rejected entry is reported exactly as it was uploaded, so it can be empty or incomplete.
        const failed: ImportTypeEntry = this.asEntry(entry?.failed_type);

        return {
            label: failed.label || failed.name || 'Unknown type',
            name: failed.name || '—',
            publicId: typeof failed.public_id === 'number' ? failed.public_id : null,
            errors: this.splitErrors(entry?.errors),
            meta: this.collectMeta(failed)
        };
    }


    private asEntry(failedType: unknown): ImportTypeEntry {
        return failedType && typeof failedType === 'object' ? failedType as ImportTypeEntry : {};
    }


    /** The backend joins several reasons into one message, so each reason becomes its own chip. */
    private splitErrors(errors: string[] | undefined): string[] {
        return (errors ?? [])
            .flatMap((error) => String(error).split(';'))
            .map((error) => error.trim())
            .filter((error) => error.length > 0);
    }


    private collectMeta(failed: ImportTypeEntry): FailedTypeMeta[] {
        const meta: FailedTypeMeta[] = [];

        if (failed.fields?.length) {
            meta.push({ label: 'Fields', value: String(failed.fields.length) });
        }

        if (failed.render_meta?.sections?.length) {
            meta.push({ label: 'Sections', value: String(failed.render_meta.sections.length) });
        }

        if (failed.version) {
            meta.push({ label: 'Version', value: failed.version });
        }

        return meta;
    }
}
