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

import { Component, Input, OnChanges, SimpleChanges, ChangeDetectorRef } from '@angular/core';
import { RenderResult } from '../../../models/cmdb-render';

@Component({
    selector: 'cmdb-object-footer',
    templateUrl: './object-footer.component.html',
    styleUrls: ['./object-footer.component.scss'],
    standalone: false
})
export class ObjectFooterComponent implements OnChanges {

  public objectID: number;
  private rr: RenderResult;

  @Input('renderResult')
  public set renderResult(rr) {
    if (rr !== undefined) {
      this.rr = rr;
      this.objectID = rr.object_information.object_id;
    }
  }

  public get renderResult() {
    return this.rr;
  }

  constructor(private changesRef: ChangeDetectorRef) {}

  public ngOnChanges(changes: SimpleChanges): void {
    this.objectID = this.renderResult.object_information.object_id;
    this.changesRef.markForCheck();
  }


}
