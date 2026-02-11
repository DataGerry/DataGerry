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

import { Component, OnInit } from '@angular/core';
import { StatusService } from '../../services/status.service';
import { CmdbStatus } from '../../models/cmdb-status';

@Component({
  selector: 'cmdb-status-list',
  templateUrl: './status-list.component.html',
  styleUrls: ['./status-list.component.scss']
})
export class StatusListComponent implements OnInit {

  public statusList: CmdbStatus[];

  constructor(private statusService: StatusService) {
  }

  public ngOnInit(): void {
    this.statusService.getStatusList().subscribe((respList: CmdbStatus[]) => {
      this.statusList = respList;
    });
  }

}
