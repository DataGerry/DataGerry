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

import { Component, inject, Input, OnInit } from '@angular/core';
import { CmdbCategoryNode } from '../../../framework/models/cmdb-category';
import { SidebarService } from '../../services/sidebar.service';

@Component({
  selector: 'cmdb-sidebar-category',
  templateUrl: './sidebar-category.component.html',
  styleUrls: ['./sidebar-category.component.scss'],
  standalone: false
})
export class SidebarCategoryComponent implements OnInit {

  public isExpanded = false;

  @Input() categoryNode: CmdbCategoryNode;

  private readonly sidebarService = inject(SidebarService);

  /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

  public ngOnInit(): void {
    this.isExpanded = this.sidebarService.isCategoryExpanded(this.categoryNode.category.public_id);
  }


  
  /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

  public toggle(): void {
    this.isExpanded = !this.isExpanded;
    this.sidebarService.setCategoryExpanded(this.categoryNode.category.public_id, this.isExpanded);
  }
}
