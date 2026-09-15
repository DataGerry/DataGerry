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
import { forkJoin, Subscription } from 'rxjs';
import { finalize } from 'rxjs/operators';
import { CmdbType } from '../../models/cmdb-type';
import { CategoryService } from '../../services/category.service';
import { TypeService } from '../../services/type.service';
import { ActivatedRoute, Params, Router } from '@angular/router';
import { CmdbCategory } from '../../models/cmdb-category';
import { CmdbMode } from '../../modes.enum';
import { SidebarService } from '../../../layout/services/sidebar.service';
import { APIGetMultiResponse } from '../../../services/models/api-response';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from '../../../layout/toast/toast.service';

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

  private categoryLoadSubscription: Subscription = new Subscription();
  private categorySubmitSubscription: Subscription = new Subscription();

  public category: CmdbCategory;
  public unAssignedTypes: CmdbType[] = [];
  public assignedTypes: CmdbType[] = [];

  public isLoading$ = this.loaderService.isLoading$;

  constructor(private categoryService: CategoryService, private typeService: TypeService,
              private router: Router, private route: ActivatedRoute, private sidebarService: SidebarService,
              private loaderService: LoaderService, private toastService: ToastService) {
    this.route.params.subscribe((params: Params) => {
      this.publicID = Number(params.publicID);
    });
  }

  public ngOnInit(): void {
    this.loaderService.show();

    // Loaded together so the category and its type lists reach the form in the same change detection run.
    this.categoryLoadSubscription = forkJoin({
      category: this.categoryService.getCategory(this.publicID),
      assigned: this.typeService.getTypeListByCategory(this.publicID),
      unassigned: this.typeService.getUncategorizedTypes()
    }).pipe(finalize(() => this.loaderService.hide()))
      .subscribe({
        next: (result: { category: CmdbCategory, assigned: CmdbType[], unassigned: APIGetMultiResponse<CmdbType> }) => {
          this.category = result.category;
          this.assignedTypes = result.assigned ?? [];
          this.unAssignedTypes = (result.unassigned?.results as Array<CmdbType>) ?? [];
        },
        error: (error) => this.toastService.error(error?.error?.message)
      });
  }

  public ngOnDestroy(): void {
    this.categoryLoadSubscription?.unsubscribe();
    this.categorySubmitSubscription?.unsubscribe();
  }

  public onSave(category: CmdbCategory): void {
    if (this.formValid) {
      this.loaderService.show();

      this.categorySubmitSubscription = this.categoryService.updateCategory(category)
        .pipe(finalize(() => this.loaderService.hide()))
        .subscribe({
          next: () => {
            this.sidebarService.loadCategoryTree();
            this.router.navigate(['/', 'framework', 'category']);
          },
          error: (error) => this.toastService.error(error?.error?.message)
        });
    }
  }

}
