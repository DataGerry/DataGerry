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

import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  OnInit,
  signal,
  TemplateRef,
  ViewChild
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subscription } from 'rxjs';
import { finalize } from 'rxjs/operators';

import { RightService } from '../services/right.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { RightOverview } from '../models/right';
import { Column, Sort } from '../../layout/table/table.types';
import { APIGetMultiResponse } from '../../services/models/api-response';
import { CollectionParameters } from '../../services/models/api-parameter';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-rights',
    templateUrl: './rights.component.html',
    styleUrls: ['./rights.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class RightsComponent implements OnInit {

  private readonly rightService = inject(RightService);
  private readonly loaderService = inject(LoaderService);
  private readonly toastService = inject(ToastService);
  private readonly destroyRef = inject(DestroyRef);

  /**
   * Component title h1.
   */
  public readonly title: string = 'Right';

  /**
   * Title small.
   */
  public readonly description: string = 'Management';

  /**
   * Current page of rights, loaded from backend.
   */
  public readonly rights = signal<Array<RightOverview>>([]);

  public readonly totalRights = signal<number>(0);

  public readonly params = signal<CollectionParameters>({ limit: 25, sort: 'name', order: 1, page: 1 });

  /**
   * Table columns.
   */
  public columns: Array<Column> = [];

  /**
   * Table Template: level column.
   */
  @ViewChild('levelTemplate', { static: true }) public levelTemplate: TemplateRef<unknown>;

  /**
   * Table Template: groups with rights column.
   */
  @ViewChild('groupsRightTemplate', { static: true }) public groupsRightTemplate: TemplateRef<unknown>;

  public readonly isLoading$ = this.loaderService.isLoading$;

  private rightsRequest?: Subscription;

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

  public ngOnInit(): void {
    this.columns = [
      {
        display: 'Name',
        name: 'name',
        data: 'name',
        sortable: true
      },
      {
        display: 'Label',
        name: 'label',
        data: 'label',
        sortable: true
      },
      {
        display: 'Description',
        name: 'description',
        data: 'description',
        sortable: true
      },
      {
        display: 'Level',
        name: 'level',
        data: 'level',
        sortable: true,
        render(data: any) {
          if (!data) {
            return '0';
          }
          return data;
        },
        template: this.levelTemplate
      },
      {
        display: 'Groups',
        name: 'groups',
        data: 'name',
        sortable: false,
        template: this.groupsRightTemplate
      }
    ] as Array<Column>;

    this.loadRights();
  }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

  public onPageChange(page: number): void {
    this.params.update(params => ({ ...params, page }));
    this.loadRights();
  }

  public onPageSizeChange(limit: number): void {
    // The page-size select re-emits when the bound limit is written back.
    if (limit === this.params().limit) {
      return;
    }
    this.params.update(params => ({ ...params, limit, page: 1 }));
    this.loadRights();
  }

  public onSortChange(sort: Sort): void {
    this.params.update(params => ({ ...params, sort: sort.name, order: sort.order }));
    this.loadRights();
  }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  private loadRights(): void {
    this.rightsRequest?.unsubscribe();
    this.loaderService.show();

    this.rightsRequest = this.rightService.getRightsOverview(this.params()).pipe(
      finalize(() => this.loaderService.hide()),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: (response: APIGetMultiResponse<RightOverview>) => {
        this.rights.set(response.results);
        this.totalRights.set(response.total);
      },
      error: () => this.toastService.error('Rights could not be loaded.')
    });
  }
}
