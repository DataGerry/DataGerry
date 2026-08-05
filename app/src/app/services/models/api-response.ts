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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

import { CmdbDao } from '../../framework/models/cmdb-dao';
import { CollectionParameters } from './api-parameter';
import { APIPager, APIPagination } from './api-pagination';


abstract class APIResponse {
  response_type: string;
  model: string;
  time: string;
}

export class APIGetSingleResponse<T = CmdbDao> extends APIResponse {
  result: T;
}

export class APIGetMultiResponse<T = CmdbDao> extends APIResponse {
  results: Array<T>;
  count: number;
  total: number;
  parameters?: CollectionParameters;
  pager?: APIPager;
  pagination?: APIPagination;
}

export class APIInsertSingleResponse<T = CmdbDao> extends APIResponse {
  result_id?: number | string;
  raw: T;
}

export class APIUpdateMultiResponse<T = CmdbDao> extends APIResponse {
  results: Array<T>;
  failed: Array<any>;
}

export class APIUpdateSingleResponse<T = CmdbDao> extends APIResponse {
  result: T;
}

export class APIDeleteSingleResponse<T = CmdbDao> extends APIResponse {
  raw: T;
}

export class APIGetListResponse<T = CmdbDao> extends APIResponse {
  results: Array<T>;
}
