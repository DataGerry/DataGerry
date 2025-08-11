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
import { CmdbType } from '../../models/cmdb-type';
import { ActivatedRoute } from '@angular/router';
import { CmdbMode } from '../../modes.enum';
import { TypeService } from '../../services/type.service';

@Component({
    selector: 'cmdb-type-edit',
    templateUrl: './type-edit.component.html',
    styleUrls: ['./type-edit.component.scss'],
    standalone: false
})
export class TypeEditComponent {

  /**
   * Type instance.
   */
  public typeInstance: CmdbType;

  /**
   * Render mode.
   */
  public mode: number = CmdbMode.Edit;

  /**
   * Start wizard index.
   */
  public stepIndex: number = 1;

  constructor(private typeService: TypeService, private route: ActivatedRoute) {
    this.route.queryParams.subscribe(params => {
      this.stepIndex = params.stepIndex || 0;
    });
    this.typeInstance = this.route.snapshot.data.type as CmdbType;
  }

}
