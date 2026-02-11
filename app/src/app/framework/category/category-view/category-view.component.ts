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
import { ReplaySubject, Subject, Subscription } from 'rxjs';
import { CategoryService } from '../../services/category.service';
import { TypeService } from '../../services/type.service';
import { CmdbMode } from '../../modes.enum';
import { ActivatedRoute, Params } from '@angular/router';
import { CmdbCategory } from '../../models/cmdb-category';
import { takeUntil } from 'rxjs/operators';

@Component({
    selector: 'cmdb-category-view',
    templateUrl: './category-view.component.html',
    styleUrls: ['./category-view.component.scss'],
    standalone: false
})
export class CategoryViewComponent implements OnInit, OnDestroy {

  public mode: CmdbMode = CmdbMode.View;
  private unSubscribe: ReplaySubject<void> = new ReplaySubject();

  public publicID: number;
  private publicIDSubject: Subject<number> = new Subject<number>();

  public category: CmdbCategory;

  constructor(private categoryService: CategoryService, private typeService: TypeService, private route: ActivatedRoute) {
    this.route.params.pipe(takeUntil(this.unSubscribe)).subscribe((params: Params) => {
      this.publicIDSubject.next(params.publicID);
    });
  }

  public ngOnInit(): void {
    this.publicIDSubject.asObservable().pipe(takeUntil(this.unSubscribe)).subscribe((publicID: number) => {
      this.publicID = publicID;
      this.categoryService.getCategory(this.publicID).pipe(
        takeUntil(this.unSubscribe)).subscribe((category: CmdbCategory) => {
          this.category = category;
        }
      );
    });
  }

  public ngOnDestroy(): void {
    this.unSubscribe?.next();
    this.unSubscribe?.complete();
  }

}
