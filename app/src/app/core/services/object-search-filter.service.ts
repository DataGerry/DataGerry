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
export class ObjectSearchFilterService {
  /**
   * Build the base match stage for a set of type IDs.
   */
  public buildTypeMatch(typeIds?: number[]): any[] {
    if (!typeIds || typeIds.length === 0) {
      return [];
    }

    return [{ $match: { type_id: { $in: typeIds } } }];
  }

  /**
   * Builds a lightweight search pipeline for pickers that read raw object: it matches the
   * public id or any stored field value. A summary line is composed on read and is not stored, so it
   * cannot be matched directly - the field values it is built from can.
   * An empty term returns no stages, which leaves the caller's own criteria untouched.
   */
  public buildFieldValueSearchPipeline(searchTerm: string): any[] {
    const normalizedTerm = (searchTerm ?? '').toString().trim();

    if (!normalizedTerm) {
      return [];
    }

    const pattern = this.escapeRegExp(normalizedTerm);

    return [
      {
        $addFields: {
          public_id_string: { $toString: '$public_id' }
        }
      },
      {
        $match: {
          $or: [
            { public_id_string: { $regex: pattern, $options: 'i' } },
            { fields: { $elemMatch: { value: { $regex: pattern, $options: 'i' } } } }
          ]
        }
      }
    ];
  }

  /**
   * Builds the aggregation pipeline used to search objects by a term.
   * When the search term is empty, this falls back to a simple type filter.
   */
  public buildSearchPipeline(searchTerm: string, typeIds?: number[]): any[] {
    const normalizedTerm = (searchTerm ?? '').toString().trim();
    const typeMatchStage = this.buildTypeMatch(typeIds);

    if (!normalizedTerm) {
      return typeMatchStage;
    }

    return [
      ...typeMatchStage,
      {
        $lookup: {
          from: 'framework.objects',
          localField: 'fields.value',
          foreignField: 'public_id',
          as: 'data'
        }
      },
      {
        $project: {
          _id: 1,
          public_id: 1,
          type_id: 1,
          active: 1,
          author_id: 1,
          creation_time: 1,
          last_edit_time: 1,
          fields: 1,
          summary_line: 1,
          type_information: 1,
          simple: {
            $reduce: {
              input: '$data.fields',
              initialValue: [],
              in: { $setUnion: ['$$value', '$$this'] }
            }
          }
        }
      },
      {
        $group: {
          _id: '$_id',
          public_id: { $first: '$public_id' },
          type_id: { $first: '$type_id' },
          active: { $first: '$active' },
          author_id: { $first: '$author_id' },
          creation_time: { $first: '$creation_time' },
          last_edit_time: { $first: '$last_edit_time' },
          fields: { $first: '$fields' },
          summary_line: { $first: '$summary_line' },
          type_information: { $first: '$type_information' },
          simple: { $first: '$simple' }
        }
      },
      {
        $project: {
          _id: '$_id',
          public_id: 1,
          type_id: 1,
          active: 1,
          author_id: 1,
          creation_time: 1,
          last_edit_time: 1,
          fields: 1,
          summary_line: 1,
          type_information: 1,
          references: { $setUnion: ['$fields', '$simple'] }
        }
      },
      {
        $addFields: {
          creationString: {
            $dateToString: {
              format: '%Y-%m-%dT%H:%M:%S.%LZ',
              date: '$creation_time'
            }
          }
        }
      },
      {
        $addFields: {
          editString: {
            $dateToString: {
              format: '%Y-%m-%dT%H:%M:%S.%LZ',
              date: '$last_edit_time'
            }
          }
        }
      },
      {
        $addFields: {
          references: {
            $map: {
              input: '$references',
              as: 'new_fields',
              in: {
                $cond: [
                  { $eq: [{ $type: '$$new_fields.value' }, 'date'] },
                  {
                    name: '$$new_fields.name',
                    value: {
                      $dateToString: {
                        format: '%Y-%m-%dT%H:%M:%S.%LZ',
                        date: '$$new_fields.value'
                      }
                    }
                  },
                  {
                    name: '$$new_fields.name',
                    value: '$$new_fields.value'
                  }
                ]
              }
            }
          }
        }
      },
      {
        $addFields: {
          public_id_string: { $toString: '$public_id' }
        }
      },
      {
        $match: {
          $or: [
            { public_id_string: { $regex: normalizedTerm, $options: 'i' } },
            { summary_line: { $regex: normalizedTerm, $options: 'i' } },
            { creationString: { $regex: normalizedTerm, $options: 'i' } },
            { editString: { $regex: normalizedTerm, $options: 'i' } },
            { references: { $elemMatch: { value: { $regex: normalizedTerm, $options: 'i' } } } }
          ]
        }
      }
    ];
  }

  /** What the user types is a literal, so its metacharacters must not act as regex operators. */
  private escapeRegExp(value: string): string {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }
}
