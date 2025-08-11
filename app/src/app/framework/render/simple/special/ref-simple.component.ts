/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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

import { Component, OnInit } from '@angular/core';
import { RenderFieldComponent } from '../../fields/components.fields';
import { ObjectService } from '../../../services/object.service';
import { RenderResult } from '../../../models/cmdb-render';
import { TypeReference } from '../../../models/cmdb-type-reference';

type TypeReferenceTemplate = {
  reference: TypeReference,
  value: any
};

@Component({
    selector: 'cmdb-ref-simple',
    templateUrl: './ref-simple.component.html',
    styleUrls: ['./ref-simple.component.scss'],
    standalone: false
})
export class RefSimpleComponent extends RenderFieldComponent implements OnInit {

  public refData: TypeReferenceTemplate = {
    reference: new TypeReference(),
    value: null
  };

  constructor(private objectService: ObjectService) {
    super();
  }

  public ngOnInit() {

    if (this.data && this.data.value && this.data.value !== 0) {
      if (!this.data.reference) {
        this.objectService.getObject(this.data.value).subscribe((res: RenderResult) => {
          this.refData = {
            reference: new TypeReference({
              type_id: res.type_information.type_id,
              object_id: res.object_information.object_id,
              icon: res.type_information.icon,
              type_label: res.type_information.type_label,
              summaries: res.summaries
            }),
            value: this.data.value,
          };
        });
      } else {
        this.refData = this.data;
      }
    } else {
      this.refData = undefined;
    }
  }
}
