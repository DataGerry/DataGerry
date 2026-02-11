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

import { Component, OnDestroy, OnInit } from '@angular/core';
import { CmdbType } from '../../models/cmdb-type';
import { TypeService } from '../../services/type.service';
import { Subscription } from 'rxjs';
import { CmdbCategory } from '../../models/cmdb-category';
import { CategoryService } from '../../services/category.service';
import { Router } from '@angular/router';
import { SidebarService } from '../../../layout/services/sidebar.service';
import { APIGetMultiResponse } from '../../../services/models/api-response';

@Component({
    selector: 'cmdb-category-add',
    templateUrl: './category-add.component.html',
    styleUrls: ['./category-add.component.scss'],
    standalone: false
})
export class CategoryAddComponent implements OnInit, OnDestroy {

  /**
   * Validation indication for button disable
   */
  public formValid: boolean = false;

  /**
   * Subscription for getUncategorizedTypes
   */
  private typeServiceSubscription: Subscription = new Subscription();

  /**
   * Subscription for category add call
   */
  private categorySubmitSubscription: Subscription = new Subscription();

  /**
   * List of uncategorized types
   */
  public unAssignedTypes: CmdbType[];
  /**
   * Instance list of types based on the ids inside the category types list
   */
  public assignedTypes: CmdbType[];

  constructor(private categoryService: CategoryService, private typeService: TypeService,
              private router: Router, private sidebarService: SidebarService) {
    this.unAssignedTypes = [];
    this.assignedTypes = [];
  }

  public ngOnInit(): void {
    this.typeServiceSubscription = this.typeService.getUncategorizedTypes().subscribe((apiResponse: APIGetMultiResponse<CmdbType>) => {
      this.unAssignedTypes = apiResponse.results as Array<CmdbType>;
    });
  }

  public ngOnDestroy(): void {
    this.typeServiceSubscription?.unsubscribe();
    this.categorySubmitSubscription?.unsubscribe();
  }

  /**
   * Call save function from service
   * @param category Raw data from form
   */
  public onSave(category: CmdbCategory): void {
    if (this.formValid) {
      this.categorySubmitSubscription = this.categoryService.postCategory(category).subscribe(() => {
        this.sidebarService.loadCategoryTree();
        this.router.navigate(['/', 'framework', 'category']);
      });
    }
  }

}
