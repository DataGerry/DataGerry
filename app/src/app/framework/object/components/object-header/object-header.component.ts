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

import { Component, inject, EventEmitter, Input, Output } from '@angular/core';
import { RenderResult } from '../../../models/cmdb-render';
import { ObjectService } from '../../../services/object.service';
import { ToastService } from '../../../../layout/toast/toast.service';
import { SidebarService } from 'src/app/layout/services/sidebar.service';

@Component({
    selector: 'cmdb-object-header',
    templateUrl: './object-header.component.html',
    styleUrls: ['./object-header.component.scss'],
    standalone: false
})
export class ObjectHeaderComponent {

  public activeState: boolean = true;
  private result: RenderResult;
  private objectID: number;

  @Output() stateChange = new EventEmitter<boolean>();

  @Input('renderResult')
  public set renderResult(result) {
    if (result !== undefined) {
      this.result = result;
      this.activeState = this.result.object_information.active;
      this.objectID = this.result.object_information.object_id;
    }
  }

  public get renderResult(): RenderResult {
    return this.result;
  }

  private readonly objectService = inject(ObjectService);
  private readonly toastService = inject(ToastService);
  private readonly sidebarService = inject(SidebarService);

  public toggleChange() {
    this.activeState = this.activeState !== true;
    this.objectService.changeState(this.objectID, this.activeState).subscribe((resp: boolean) => {
      this.toastService.info(`Changed active state to ${ this.activeState }`);
      this.stateChange.emit(true);
    });
    this.sidebarService.ReloadSideBarData();
  }


}
