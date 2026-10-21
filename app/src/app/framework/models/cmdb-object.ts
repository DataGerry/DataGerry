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
import { SpecialType } from './special-type';


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


/**
 * Partial-update payload for the object PATCH route.
 * Every key is optional, but the request must carry at least one field or
 * multi_data_section change (see the object PATCH endpoint contract).
 */
export interface ObjectPatchPayload {
    fields?: MultiDataSectionFieldValue[];
    created_mds_rows?: ObjectPatchCreatedRow[];
    edited_mds_rows?: ObjectPatchEditedRow[];
    deleted_mds_rows?: ObjectPatchDeletedRow[];
    /** Label for the object's location; only sent when the object actually has a location. */
    location_name?: string;
    comment?: string;
}


/** A brand new multi_data_section row. The multi_data_id is assigned by the backend. */
export interface ObjectPatchCreatedRow {
    section_id: string;
    data: MultiDataSectionFieldValue[];
}


/** An existing multi_data_section row identified by its multi_data_id. */
export interface ObjectPatchEditedRow {
    section_id: string;
    multi_data_id: number;
    data: MultiDataSectionFieldValue[];
}


/** A multi_data_section row to remove, identified by its multi_data_id. */
export interface ObjectPatchDeletedRow {
    section_id: string;
    multi_data_id: number;
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
    public special_type?: SpecialType;
    public creation_time: any;
    public last_edit_time: any;
    public author_name?: string;
    public comment?: string;
    /** Label for the object's location, sent alongside the dg_location field on create. */
    public location_name?: string;
}
