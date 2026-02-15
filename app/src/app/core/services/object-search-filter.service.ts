import { Injectable } from '@angular/core';

@Injectable({
  providedIn: 'root'
})
export class ObjectSearchFilterService {
  /**
   * Build the base match stage for a set of type IDs.
   */
  public buildTypeMatch(typeIds: number[]): any[] {
    return [{ $match: { type_id: { $in: typeIds } } }];
  }

  /**
   * Builds the aggregation pipeline used to search objects by a term.
   * When the search term is empty, this falls back to a simple type filter.
   */
  public buildSearchPipeline(searchTerm: string, typeIds: number[]): any[] {
    const normalizedTerm = (searchTerm ?? '').toString().trim();
    if (!normalizedTerm) {
      return this.buildTypeMatch(typeIds);
    }

    return [
      { $match: { type_id: { $in: typeIds } } },
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
}
