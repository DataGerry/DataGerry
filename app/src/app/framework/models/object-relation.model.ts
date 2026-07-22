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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

/** Role of the currently viewed object within a relation. */
export type ObjectRelationRole = 'parent' | 'child';


export interface ObjectRelationTab {
  relation_id: number;
  role: ObjectRelationRole;
  label: string;
  icon: string;
  color: string;
  count: number;
}

/** Counterpart object */
export interface ObjectRelationCounterpart {
  object_id: number;
  type_label: string;
  icon: string;
  summary_line: string;
}

/** A single paginated relation instance row for a tab. */
export interface ObjectRelationRow {
  public_id: number;
  relation_id: number;
  field_values: Array<{ name: string; value: any }>;
  counterpart: ObjectRelationCounterpart;
}

/** Response shape of the paginated instances endpoint. */
export interface ObjectRelationInstancesResponse {
  total: number;
  count: number;
  results: ObjectRelationRow[];
}

/** Query parameters for `GET /object_relations/tabs/<object_id>/instances`. */
export interface ObjectRelationInstancesQuery {
  relationId: number;
  role: ObjectRelationRole;
  page: number;
  limit: number;
  sort: string;
  order: number;
}

/** Builds the stable per-tab identity used for tab tracking/selection. */
export function objectRelationTabKey(tab: Pick<ObjectRelationTab, 'relation_id' | 'role'>): string {
  return `${tab.relation_id}:${tab.role}`;
}
