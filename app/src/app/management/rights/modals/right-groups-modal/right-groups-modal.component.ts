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

import { Component, inject, Input, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { RightOverview } from '../../../models/right';
import { Column } from '../../../../layout/table/table.types';

@Component({
    selector: 'cmdb-right-groups-modal',
    templateUrl: './right-groups-modal.component.html',
    styleUrls: ['./right-groups-modal.component.scss'],
    standalone: false
})
export class RightGroupsModalComponent implements OnInit {

  @Input() public right: RightOverview;

  @ViewChild('usersTemplate', { static: true }) public usersTemplate: TemplateRef<unknown>;

  public columns: Array<Column> = [];

  public readonly activeModal = inject(NgbActiveModal);

  public ngOnInit(): void {
    this.columns = [
      {
        display: 'Public ID',
        name: 'public_id',
        data: 'public_id',
        sortable: false
      },
      {
        display: 'Name',
        name: 'name',
        data: 'name',
        sortable: false
      },
      {
        display: 'Label',
        name: 'label',
        data: 'label',
        sortable: false
      },
      {
        display: 'Users',
        name: 'users',
        data: 'public_id',
        sortable: false,
        fixed: true,
        template: this.usersTemplate,
        cssClasses: ['text-center']
      }
    ] as Array<Column>;
  }

}
