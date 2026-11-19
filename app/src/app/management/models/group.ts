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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { CmdbDao } from '../../framework/models/cmdb-dao';
import { Right } from './right';

export class Group implements CmdbDao {

  public readonly public_id: number;
  public name: string;
  public label: string;
  public rights: Array<Right | any>;

}

export interface GroupUsage {
  members: number;
  /** Members for whom this is their only group; a delete action applies only to them. */
  sole_members: number;
  ldap_default_group: boolean;
  ldap_group_mappings: Array<unknown>;
  sole_grantee_type_ids: Array<number>;
  acl_type_ids: Array<number>;
  blocks_delete: boolean;
}
