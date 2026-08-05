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

import { Injectable } from '@angular/core';
import { BreadcrumbItem } from './breadcrumb.model';
import { BehaviorSubject } from 'rxjs';
import { TypeService } from '../../../framework/services/type.service';
import { ObjectService } from '../../../framework/services/object.service';
import { RenderResult } from '../../../framework/models/cmdb-render';

@Injectable()
export class BreadcrumbService {

  public breadcrumbsSource: BehaviorSubject<BreadcrumbItem[]>;

  constructor(private typeService: TypeService, private objService: ObjectService) {
    this.breadcrumbsSource = new BehaviorSubject<BreadcrumbItem[]>([]);
  }

  public store(breadcrumbs: BreadcrumbItem[]) {
    if (breadcrumbs) {
      //  Exceptions for type Routes
      const typeLabel = breadcrumbs.find(x => x.label === 'Object Type List');
      if (typeLabel && typeLabel.params.publicID !== undefined) {
        this.typeService.getType(typeLabel.params.publicID).subscribe(type => typeLabel.label = type.label);
      }

      const typeViewLabel = breadcrumbs.find(x => x.label === 'Type View');
      if (typeViewLabel && typeViewLabel.params.publicID !== undefined) {
        typeViewLabel.label = 'View';
        this.objService.getObject(breadcrumbs[breadcrumbs.length - 1].params.publicID).subscribe((test: RenderResult) => {
          breadcrumbs[breadcrumbs.length - 2].url = 'object/type/' + test.type_information.type_id;
          breadcrumbs[breadcrumbs.length - 2].label = test.type_information.type_label;
        });
      }
      this.breadcrumbsSource.next(breadcrumbs);
    }
  }

  public get() {
    return this.breadcrumbsSource;
  }
}
