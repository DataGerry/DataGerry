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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { Component, Input } from '@angular/core';
import { RenderResult } from '../../../models/cmdb-render';


class MetaView {
  private readonly headers: { [key: string]: object | string | number }[] = [
    {'Public ID': this.objectID},
    {'Type ID': this.typeID},
    {'Type Name': this.typeName},
    {'Creation Time': this.creationTime},
    {'Author ID': this.authorID},
    {'Author Name': this.authorName}
  ];

  constructor(public objectID: number, public typeID: number, public typeName, public creationTime: string,
              public authorID: number, public authorName) {
  }

  public get headerLine() {
    return this.headers;
  }
}

@Component({
    selector: 'cmdb-object-view-meta',
    templateUrl: './object-view-meta.component.html',
    styleUrls: ['./object-view-meta.component.scss'],
    standalone: false
})
export class ObjectViewMetaComponent {

  public meteObject: MetaView = null;
  private _renderResult: any;

  @Input('renderResult')
  public set renderResult(data: RenderResult) {
    if (data !== undefined) {
      this._renderResult = data;
      this.meteObject = new MetaView(
        this.renderResult.object_information.object_id,
        this.renderResult.type_information.type_id,
        this.renderResult.type_information.type_label,
        this.renderResult.object_information.creation_time.$date,
        this.renderResult.object_information.author_id,
        this.renderResult.object_information.author_name,
      );
    }

  }

  public get renderResult(): RenderResult {
    return this._renderResult;
  }

  public isObject(value: object | string | number) {
    return typeof value === 'object';
  }


}




