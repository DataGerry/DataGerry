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
import { RenderResult } from '../../../framework/models/cmdb-render';
/* ------------------------------------------------------------------------------------------------------------------ */

export class SearchResult {
    public result: RenderResult;
    public matches: any[];
}

export class SearchResultList {
    public limit: number;
    public skip?: number;
    public total_results: number;
    public results?: SearchResult[];
    public groups?: any[];
}


export class NumberSearchResults implements Object {
    public active: number = 0;
    public inactive: number = 0;
    public total: number = 0;

    public constructor(init?: Partial<NumberSearchResults>) {
        Object.assign(this, init);
    }
}