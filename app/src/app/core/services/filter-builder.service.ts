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
import { Injectable } from '@angular/core';

@Injectable({
  providedIn: 'root'
})
export class FilterBuilderService {

  constructor() { }

  /**
   * Builds a MongoDB-like aggregation pipeline query for text-based searching
   * on specified fields.
   * 
   * @param filterValue The text to filter by (e.g. from a search box).
   * @param fields An array of fields that should be filtered on. 
   *               Each item can describe how to handle that field
   *               (e.g., direct string, array, etc.).
   * @returns an array representing the MongoDB pipeline `$match` stage.
   * 
   * Example usage:
   *   buildFilter('foo', [
   *     { name: 'public_id', isArray: false },
   *     { name: 'categories', isArray: true },
   *   ]);
   */
  public buildFilter(
    filterValue: string,
    fields: Array<{ name: string; isArray?: boolean }>
  ): any[] {
    const query: any[] = [];

    if (!filterValue) {
      return query; // no filter
    }

    const orConditions: any[] = [];

    // Convert to string once, for safety
    const filterString = String(filterValue);

    fields.forEach(field => {
      if (field.isArray) {
        orConditions.push({
          [field.name]: {
            $elemMatch: {
              $regex: filterString,
              $options: 'i'
            }
          }
        });
      } else {
        // Simple string field
        orConditions.push({
          [field.name]: {
            $regex: filterString,
            $options: 'i'
          }
        });
      }
    });

    if (orConditions.length) {
      query.push({ $match: { $or: orConditions } });
    }

    return query;
  }
}
