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

/** Whether the uploaded types are inserted as new ones or applied onto existing ones. */
export type ImportTypeAction = 'create' | 'update';


/**
 * A single entry of an uploaded type export.
 */
export interface ImportTypeEntry {
    public_id?: number;
    name?: string;
    label?: string;
    version?: string;
    fields?: { name?: string; label?: string; type?: string }[];
    render_meta?: {
        icon?: string;
        sections?: { name?: string; label?: string }[];
    };
    [key: string]: unknown;
}


/** One rejected entry of the import report: the data the user uploaded plus the reasons. */
export interface ImportTypeFailedEntry {
    failed_type: ImportTypeEntry;
    errors: string[];
}


/** Partial report both the create and the update route answer with. */
export class ImportTypeResponse {
    message?: string;
    success_imports = 0;
    failed_imports: ImportTypeFailedEntry[] = [];
}
