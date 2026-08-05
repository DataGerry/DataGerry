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
import { CmdbDao } from './cmdb-dao';
/* ------------------------------------------------------------------------------------------------------------------ */

export interface Field{
    type:string;
    name: string;
    label: string;
}

/* ------------------------------------------------------------------------------------------------------------------ */

export class CmdbSectionTemplate implements CmdbDao {
    public public_id: number;
    public name: string;
    public label: string;
    public fields: Field[];
    public is_global: boolean = false;
    public predefined: boolean = false;
    public type: string = 'section' //don't change this, it is required due compability
}