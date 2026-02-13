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
/* ------------------------------------------------------------------------------------------------------------------ */
import { CmdbDao } from './cmdb-dao';


export interface MultiDataSectionFieldValue {
    name: string;
    value: any;
}


export interface MultiDataSectionSet {
    multi_data_id: number;
    data: MultiDataSectionFieldValue[];
}


export interface MultiDataSectionEntry {
    section_id: string;
    highest_id: number;
    values: MultiDataSectionSet[];
}

/* ------------------------------------------------------------------------------------------------------------------ */

export class CmdbObject implements CmdbDao {
    public public_id: number;
    public type_id: number;
    public ci_explorer_tooltip: string;
    public status: boolean = true;
    public version: string;
    public author_id: number;
    public editor_id?: number;
    public active: boolean;
    public fields: any[];
    public multi_data_sections: MultiDataSectionEntry[] = [];
    public creation_time: any;
    public last_edit_time: any;
    public author_name?: string;
    public comment?: string;
}
