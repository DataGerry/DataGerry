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

import { Component, OnDestroy, OnInit } from '@angular/core';
import { Subscription } from 'rxjs';
import { CmdbType } from '../../models/cmdb-type';
import { CategoryService } from '../../services/category.service';
import { TypeService } from '../../services/type.service';
import { ActivatedRoute, Params, Router } from '@angular/router';
import { CmdbCategory } from '../../models/cmdb-category';
import { CmdbMode } from '../../modes.enum';
import { SidebarService } from '../../../layout/services/sidebar.service';
import { APIGetMultiResponse } from '../../../services/models/api-response';

@Component({
    selector: 'cmdb-category-edit',
    templateUrl: './category-edit.component.html',
    styleUrls: ['./category-edit.component.scss'],
    standalone: false
})
export class CategoryEditComponent implements OnInit, OnDestroy {

  public formValid: boolean = false;
  public publicID: number;
  public mode: CmdbMode = CmdbMode.Edit;

  private categoryServiceSubscription: Subscription = new Subscription();
  private typeUnAssignedSubscription: Subscription = new Subscription();
  private typeAssignedSubscription: Subscription = new Subscription();
  private categorySubmitSubscription: Subscription = new Subscription();

  public category: CmdbCategory;
  public unAssignedTypes: CmdbType[] = [];
  public assignedTypes: CmdbType[] = [];

  constructor(private categoryService: CategoryService, private typeService: TypeService,
              private router: Router, private route: ActivatedRoute, private sidebarService: SidebarService) {
    this.route.params.subscribe((params: Params) => {
      this.publicID = Number(params.publicID);
    });
  }

  public ngOnInit(): void {
    this.categoryServiceSubscription = this.categoryService.getCategory(this.publicID).subscribe((category: CmdbCategory) => {
      this.category = category;

    });
    this.typeAssignedSubscription = this.typeService.getTypeListByCategory(this.publicID).subscribe((types: CmdbType[]) => {
      this.assignedTypes = types;
    });

    this.typeUnAssignedSubscription = this.typeService.getUncategorizedTypes().subscribe((apiResponse: APIGetMultiResponse<CmdbType>) => {
      this.unAssignedTypes = apiResponse.results;
    });
  }

  public ngOnDestroy(): void {
    this.categoryServiceSubscription?.unsubscribe();
    this.typeUnAssignedSubscription?.unsubscribe();
    this.typeAssignedSubscription?.unsubscribe();
    this.categorySubmitSubscription?.unsubscribe();
  }

  public onSave(category: CmdbCategory): void {
    if (this.formValid) {
      this.categorySubmitSubscription = this.categoryService.updateCategory(category).subscribe(() => {
        this.sidebarService.loadCategoryTree();
        this.router.navigate(['/', 'framework', 'category']);
      });
    }
  }

}
