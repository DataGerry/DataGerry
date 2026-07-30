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

export class ImporterFile {
    file: File = undefined;
    fileContent: string | ArrayBuffer = undefined;
    fileFormat: string = undefined;
    fileName: string = '';
}


export class ImporterConfig {
    mapping: {} = {};
    type_id: number = undefined;
    start_element: number = 0;
    max_elements: number = 0;
    overwrite_public: boolean = false;
}


export interface UnsupportedImportFieldGroup {
    kind: string;
    names: string;
}


export interface ImportObjectField {
    name: string;
    value: any;
    type?: string;
}


export interface ImportObjectData {
    public_id?: number;
    type_id?: number;
    type_label?: string;
    active?: boolean;
    fields?: ImportObjectField[];
    multi_data_sections?: any[];
    [key: string]: any;
}


export interface ImportFailedEntry {
    failed_object: ImportObjectData;
    errors: string[];
}


export class ImportResponse {
    message?: string;
    success_imports = 0;
    failed_imports: ImportFailedEntry[] = [];
}
