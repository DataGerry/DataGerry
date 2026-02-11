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

import { Component, Input, OnDestroy, OnInit } from '@angular/core';
import { CmdbType } from '../../../framework/models/cmdb-type';
import { Subscription } from 'rxjs';
import { ObjectService } from '../../../framework/services/object.service';
import { SidebarService } from '../../services/sidebar.service';

@Component({
    selector: 'cmdb-sidebar-type',
    templateUrl: './sidebar-type.component.html',
    styleUrls: ['./sidebar-type.component.scss'],
    standalone: false
})
export class SidebarTypeComponent implements OnInit, OnDestroy {

  @Input() public type: CmdbType;

  public objectCounter: unknown = 0;

  public constructor(private objectService: ObjectService, private sidebarService: SidebarService) {
  }

  public ngOnInit() {
    this.sidebarService.initializeCounter(this);
  }

  public ngOnDestroy() {
    this.sidebarService?.deleteCounter(this);
  }

}
