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

import { Pipe, PipeTransform } from '@angular/core';
import { CmdbCategoryTree } from '../../framework/models/cmdb-category';

@Pipe({
    name: 'categoryTreeFilter',
    standalone: false
})

export class CategoryTreeFilterPipe implements PipeTransform {

  /**
   * Filter the category tree structure by category label
   * Letters will be transformed to lowercase.
   */
  transform(categoryTree: CmdbCategoryTree, label: string): any {
    return categoryTree.filter(node =>
      node.category.label.toLowerCase().includes(label.toLowerCase()));
  }
}
