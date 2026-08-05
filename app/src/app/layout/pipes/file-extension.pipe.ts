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

@Pipe({
    name: 'fileExtension',
    standalone: false
})
export class FileExtensionPipe implements PipeTransform {

  private iconList = [
    { type: ['xlsx'], icon: 'fa fa-file-excel-o' },
    { type: ['pdf'], icon: 'fa fa-file-pdf-o' },
    { type: ['csv'], icon: 'fas fa-file-csv' },
    { type: ['gif', 'png', 'jpg', 'jpeg'], icon: 'fa fa-file-image-o' },
    { type: ['ppt', 'pptx'], icon: 'far fa-file-powerpoint'},
    { type: ['doc', 'docx'], icon: 'far fa-file-word'}
  ];

  /**
   * Converts input values into fontawesome i-tags.
   * Creates ICONS based on the document extension.
   */
  transform(filename: any): any {
    const ext = filename.split('.').pop();
    const obj = this.iconList.filter(row => {
      if (row.type.includes(ext)) {
        return true;
      }
    });
    if (obj.length > 0) {
      return obj[0].icon;
    } else {
      return 'far fa-file-code';
    }
  }

}
