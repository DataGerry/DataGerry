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
  computed,
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
import { ObjectRelationTableConfigService } from 'src/app/framework/services/object-relation-table-config.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { Column, Sort, SortDirection, TableState, TableStatePayload } from 'src/app/layout/table/table.types';
import { ObjectRelationRow, ObjectRelationTab } from 'src/app/framework/models/object-relation.model';
import { CmdbRelation, RelationField } from 'src/app/framework/models/relation.model';

const DEFAULT_SORT = 'public_id';
const DEFAULT_PAGE_SIZE = 10;

/**
 * Renders a single relation tab: the paginated instances of one relation, with the
 * relation's own fields available as optional columns.
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
  public readonly pageSize = signal(DEFAULT_PAGE_SIZE);
  public readonly selectedIds = signal<number[]>([]);

  public readonly columns = signal<Column[]>([]);
  public readonly initialVisibleColumns = signal<string[]>([]);
  public readonly tableSort = signal<Sort>({ name: DEFAULT_SORT, order: SortDirection.ASCENDING });
  public readonly tableStates = signal<TableState[]>([]);
  public readonly tableState = signal<TableState | undefined>(undefined);
  public readonly stateUrl = computed(() => this.tableConfigService.getStateUrl(this.tab()));
  public readonly stateId = ObjectRelationTableConfigService.STATE_PAYLOAD_ID;

  @ViewChild('typeTemplate', { static: true }) private typeTemplate!: TemplateRef<any>;
  @ViewChild('counterpartTemplate', { static: true }) private counterpartTemplate!: TemplateRef<any>;
  @ViewChild('fieldTemplate', { static: true }) private fieldTemplate!: TemplateRef<any>;
  @ViewChild('actionsTemplate', { static: true }) private actionsTemplate!: TemplateRef<any>;

  private initialized = false;

  // Relation definition of the active tab, kept to rebuild the columns without a refetch.
  private relation: CmdbRelation | null = null;

  private readonly destroy$ = new Subject<void>();
  // Cancels every pending request of a tab that is no longer the active one.
  private readonly reloadTab$ = new Subject<void>();
  // Cancels a page request that a newer one supersedes.
  private readonly reload$ = new Subject<void>();

  private readonly relationService = inject(ObjectRelationService);
  private readonly tableConfigService = inject(ObjectRelationTableConfigService);
  private readonly toastService = inject(ToastService);
  private readonly loaderService = inject(LoaderService);

  /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

  ngOnInit(): void {
    // The column templates are only resolved from here on, so the first load runs
    // in ngOnInit and ngOnChanges takes over from the second one.
    this.initialized = true;
    this.loadTab();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (this.initialized && (changes['tab'] || changes['objectId'])) {
      this.resetState();
      this.loadTab();
    }
  }

  ngOnDestroy(): void {
    this.reload$.next();
    this.reload$.complete();
    this.reloadTab$.next();
    this.reloadTab$.complete();
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
    this.tableSort.set({ name: sort?.name || DEFAULT_SORT, order: sort?.order ?? SortDirection.ASCENDING });
    this.page.set(1);
    this.loadInstances();
  }

  public onSelectionChange(selected: ObjectRelationRow[]): void {
    this.selectedIds.set((selected || []).map(row => row.public_id));
  }

  /** Applies a saved layout. */
  public onStateSelect(state: TableState): void {
    this.tableState.set(state);
    this.applyState(state);
    this.buildColumns();
    this.loadInstances();
  }

  /** Restores the tab defaults: base columns only, first page, sorted by id. */
  public onStateReset(): void {
    this.tableState.set(undefined);
    this.resetState();
    this.buildColumns();
    this.loadInstances();
  }

  public onStateSave(state: TableState): void {
    this.syncStates(state);
  }

  public onStateUpdate(state: TableState): void {
    this.syncStates(state);
  }

  public onStateDelete(state: TableState): void {
    const current = this.tableState()?.name === state.name ? undefined : this.tableState();
    this.syncStates(current);
  }

  public onDeleteSelected(): void {
    const selected = this.rows().filter(row => this.selectedIds().includes(row.public_id));
    if (selected.length) {
      this.removeSelected.emit(selected);
    }
  }

  /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

  /** Cell text of a relation field: choice fields resolve to their option label. */
  public displayValue(field: RelationField, value: unknown): string {
    if (Array.isArray(value)) {
      return value.map(entry => this.displayValue(field, entry)).join(', ');
    }

    const option = field?.options?.find(entry => entry.name === value);

    return option ? option.label : String(value);
  }

  /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  /** The table persists the layouts and updates the list it was given; republish it. */
  private syncStates(current: TableState | undefined): void {
    this.tableStates.set([...this.tableStates()]);
    this.tableState.set(current);
  }

  /**
   * Reads the saved layouts first, so the last used one is applied before the
   * columns are built and the first page is requested.
   */
  private loadTab(): void {
    const tab = this.tab();

    if (!tab) {
      return;
    }

    this.reloadTab$.next();

    this.tableConfigService.getStatePayload(tab)
      .pipe(takeUntil(merge(this.destroy$, this.reloadTab$)))
      .subscribe((payload: TableStatePayload | undefined) => {
        this.tableStates.set(payload?.tableStates ?? []);
        this.tableState.set(payload?.currentState);
        this.applyState(payload?.currentState);
        this.loadRelationColumns(tab);
        this.loadInstances();
      });
  }

  /** A layout carries a page number as well, but a tab always opens on the first page. */
  private applyState(state: TableState | undefined): void {
    if (!state) {
      return;
    }

    if (state.pageSize) {
      this.pageSize.set(state.pageSize);
    }

    if (state.sort?.name) {
      this.tableSort.set({ name: state.sort.name, order: state.sort.order ?? SortDirection.ASCENDING });
    }
  }

  private loadInstances(): void {
    const objectId = this.objectId();
    const tab = this.tab();
    if (!objectId || !tab) {
      return;
    }

    // Drop a page request that is already on its way.
    this.reload$.next();

    this.loading.set(true);
    this.loaderService.show();
    this.relationService.getRelationTabInstances(objectId, {
      relationId: tab.relation_id,
      role: tab.role,
      page: this.page(),
      limit: this.pageSize(),
      sort: this.tableSort().name,
      order: this.tableSort().order
    })
      .pipe(takeUntil(merge(this.destroy$, this.reloadTab$, this.reload$)), finalize(() => {
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
    this.pageSize.set(DEFAULT_PAGE_SIZE);
    this.tableSort.set({ name: DEFAULT_SORT, order: SortDirection.ASCENDING });
    this.selectedIds.set([]);
  }

  /**
   * Loads the relation definition and turns its fields into optional columns. The
   * table stays usable with the base columns while the request runs.
   */
  private loadRelationColumns(tab: ObjectRelationTab): void {
    this.relation = null;
    this.buildColumns();
    this.loaderService.show();

    this.tableConfigService.getRelation(tab.relation_id)
      .pipe(takeUntil(merge(this.destroy$, this.reloadTab$)), finalize(() => this.loaderService.hide()))
      .subscribe({
        next: (relation) => {
          this.relation = relation;
          this.buildColumns();
        },
        error: (err) => this.toastService.error(err?.error?.message)
      });
  }

  private buildColumns(): void {
    const columns: Column[] = [
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
      }
    ];

    for (const field of this.tableConfigService.getOrderedFields(this.relation)) {
      columns.push(this.buildFieldColumn(field));
    }

    columns.push({
      display: 'Actions',
      name: 'actions',
      data: 'actions',
      template: this.actionsTemplate,
      sortable: false,
      fixed: true,
      style: { width: '150px', 'text-align': 'center' }
    });

    // Default layout the column reset falls back to: base columns only.
    this.initialVisibleColumns.set(columns.filter(column => !column.hidden).map(column => column.name));
    this.applyStateColumns(columns);
    this.columns.set(columns);
  }

  /** Field values are a list on the row, so the cell resolves them by field name. */
  private buildFieldColumn(field: RelationField): Column {
    return {
      display: field.label || field.name,
      name: `fields.${field.name}`,
      data: 'field_values',
      type: field.type,
      sortable: false,
      searchable: false,
      hidden: true,
      template: this.fieldTemplate,
      style: { width: 'auto', 'text-align': 'left' },
      render: (fieldValues: ObjectRelationRow['field_values']) => ({
        field,
        value: (fieldValues || []).find(entry => entry.name === field.name)?.value ?? null
      })
    };
  }

  private applyStateColumns(columns: Column[]): void {
    const visible = this.tableState()?.visibleColumns;

    if (!visible?.length) {
      return;
    }

    for (const column of columns) {
      column.hidden = !column.fixed && !visible.includes(column.name);
    }
  }
}
