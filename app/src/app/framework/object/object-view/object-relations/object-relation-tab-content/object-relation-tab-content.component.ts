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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import {
  ChangeDetectionStrategy,
  Component,
  OnChanges,
  OnDestroy,
  OnInit,
  SimpleChanges,
  TemplateRef,
  ViewChild,
  inject,
  input,
  output,
  signal
} from '@angular/core';
import { Subject, finalize, merge, takeUntil } from 'rxjs';

import { ObjectRelationService } from 'src/app/framework/services/object-relation.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { Column, Sort } from 'src/app/layout/table/table.types';
import { ObjectRelationRow, ObjectRelationTab } from 'src/app/framework/models/object-relation.model';

/**
 * Renders a single relation tab: one paginated
 */
@Component({
  selector: 'cmdb-object-relation-tab-content',
  templateUrl: './object-relation-tab-content.component.html',
  styleUrls: ['./object-relation-tab-content.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  standalone: false
})
export class ObjectRelationTabContentComponent implements OnInit, OnChanges, OnDestroy {

  /* --------------------------------------------------- INPUTS / OUTPUTS --------------------------------------------------- */

  public readonly objectId = input.required<number>();
  public readonly tab = input.required<ObjectRelationTab>();

  public readonly add = output<void>();
  public readonly view = output<ObjectRelationRow>();
  public readonly edit = output<ObjectRelationRow>();
  public readonly copy = output<ObjectRelationRow>();
  public readonly remove = output<ObjectRelationRow>();
  public readonly removeSelected = output<ObjectRelationRow[]>();

  /* --------------------------------------------------- PUBLIC STATE --------------------------------------------------- */

  public readonly rows = signal<ObjectRelationRow[]>([]);
  public readonly total = signal(0);
  public readonly loading = signal(false);
  public readonly page = signal(1);
  public readonly pageSize = signal(10);
  public readonly selectedIds = signal<number[]>([]);

  public columns: Column[] = [];

  @ViewChild('typeTemplate', { static: true }) private typeTemplate!: TemplateRef<any>;
  @ViewChild('counterpartTemplate', { static: true }) private counterpartTemplate!: TemplateRef<any>;
  @ViewChild('actionsTemplate', { static: true }) private actionsTemplate!: TemplateRef<any>;

  private sort = 'public_id';
  private order = 1;
  private readonly destroy$ = new Subject<void>();
  // Emits before each load to cancel any request that a newer load supersedes.
  private readonly reload$ = new Subject<void>();

  private readonly relationService = inject(ObjectRelationService);
  private readonly toastService = inject(ToastService);
  private readonly loaderService = inject(LoaderService);

  /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

  ngOnInit(): void {
    this.buildColumns();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['tab'] || changes['objectId']) {
      this.resetState();
      this.loadInstances();
    }
  }

  ngOnDestroy(): void {
    this.reload$.next();
    this.reload$.complete();
    this.destroy$.next();
    this.destroy$.complete();
  }

  /* --------------------------------------------------- EVENTS --------------------------------------------------- */

  public onPageChange(page: number): void {
    this.page.set(page);
    this.loadInstances();
  }

  public onPageSizeChange(pageSize: number): void {
    this.pageSize.set(pageSize);
    this.page.set(1);
    this.loadInstances();
  }

  public onSortChange(sort: Sort): void {
    this.sort = sort?.name || 'public_id';
    this.order = sort?.order ?? 1;
    this.page.set(1);
    this.loadInstances();
  }

  public onSelectionChange(selected: ObjectRelationRow[]): void {
    this.selectedIds.set((selected || []).map(row => row.public_id));
  }

  public onDeleteSelected(): void {
    const selected = this.rows().filter(row => this.selectedIds().includes(row.public_id));
    if (selected.length) {
      this.removeSelected.emit(selected);
    }
  }

  /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  private loadInstances(): void {
    const objectId = this.objectId();
    const tab = this.tab();
    if (!objectId || !tab) {
      return;
    }

    // Cancel a still-pending request from a previous tab/page before starting.
    this.reload$.next();

    this.loading.set(true);
    this.loaderService.show();
    this.relationService.getRelationTabInstances(objectId, {
      relationId: tab.relation_id,
      role: tab.role,
      page: this.page(),
      limit: this.pageSize(),
      sort: this.sort,
      order: this.order
    })
      .pipe(takeUntil(merge(this.destroy$, this.reload$)), finalize(() => {
        this.loading.set(false);
        this.loaderService.hide();
      }))
      .subscribe({
        next: (response) => {
          this.rows.set(response.results);
          this.total.set(response.total);
          this.selectedIds.set([]);
        },
        error: (err) => this.toastService.error(err?.error?.message)
      });
  }

  private resetState(): void {
    this.page.set(1);
    this.sort = 'public_id';
    this.order = 1;
    this.selectedIds.set([]);
  }

  private buildColumns(): void {
    this.columns = [
      {
        display: 'Object Relation ID',
        name: 'public_id',
        data: 'public_id',
        sortable: true,
        searchable: false,
        style: { width: '180px', 'text-align': 'center' }
      },
      {
        display: 'Type',
        name: 'type',
        data: 'counterpart',
        template: this.typeTemplate,
        sortable: false,
        style: { width: 'auto', 'text-align': 'left' }
      },
      {
        display: 'Relation Object',
        name: 'counterpart',
        data: 'counterpart',
        template: this.counterpartTemplate,
        sortable: false,
        style: { width: 'auto', 'text-align': 'left' }
      },
      {
        display: 'Actions',
        name: 'actions',
        data: 'actions',
        template: this.actionsTemplate,
        sortable: false,
        style: { width: '150px', 'text-align': 'center' }
      }
    ];
  }
}
