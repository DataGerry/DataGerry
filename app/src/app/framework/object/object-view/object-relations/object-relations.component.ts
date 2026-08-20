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
  SimpleChanges,
  computed,
  contentChildren,
  inject,
  input,
  signal
} from '@angular/core';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { Subject, finalize, takeUntil } from 'rxjs';

import { CmdbMode } from 'src/app/framework/modes.enum';
import { ObjectRelationService } from 'src/app/framework/services/object-relation.service';
import { RelationService } from 'src/app/framework/services/relaion.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { CoreDeleteConfirmationModalComponent } from 'src/app/core/components/dialog/delete-dialog/core-delete-confirmation-modal.component';
import { ObjectRelationSelectModalComponent } from './object-relation-select-modal/object-relation-select-modal.component';
import { ExtendedRelation } from 'src/app/framework/models/object.model';
import {
  ObjectRelationRole,
  ObjectRelationRow,
  ObjectRelationTab,
  objectRelationTabKey
} from 'src/app/framework/models/object-relation.model';
import { ObjectTabDirective } from './object-tab.directive';

interface RelationSelection {
  relation: ExtendedRelation;
  role: ObjectRelationRole;
}

interface RelationFocus {
  relationId: number;
  role: ObjectRelationRole;
}

const ATTRIBUTES_KEY = 'attributes';

/**
 * Orchestrates the object-relations panel: it owns the single tab strip
 * (Attributes is projected via <ng-content>, the host may contribute further
 * tabs with `cmdbObjectTab`, relation tabs come from
 * `GET /object_relations/tabs/<object_id>`), delegates a tab's paginated table
 * to the tab-content child, and coordinates the create/edit/copy/delete dialogs.
 */
@Component({
  selector: 'cmdb-object-relations',
  templateUrl: './object-relations.component.html',
  styleUrls: ['./object-relations.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  standalone: false
})
export class ObjectRelationsComponent implements OnChanges, OnDestroy {

  /* --------------------------------------------------- INPUTS --------------------------------------------------- */

  public readonly objectId = input.required<number>();
  public readonly typeId = input.required<number>();

  /* --------------------------------------------------- PUBLIC STATE --------------------------------------------------- */

  /** Tabs the host contributes; their content is rendered beside the relation tables. */
  public readonly hostTabs = contentChildren(ObjectTabDirective);

  public readonly tabs = signal<ObjectRelationTab[]>([]);
  public readonly activeKey = signal<string>(ATTRIBUTES_KEY);

  public readonly activeTab = computed<ObjectRelationTab | null>(() => {
    const key = this.activeKey();
    if (key === ATTRIBUTES_KEY || this.isHostTab(key)) {
      return null;
    }
    return this.tabs().find((tab) => objectRelationTabKey(tab) === key) ?? null;
  });

  /** A key that matches nothing left falls back here, so the body is never blank. */
  public readonly isAttributesActive = computed(() => {
    const key = this.activeKey();
    return key === ATTRIBUTES_KEY || (!this.isHostTab(key) && !this.activeTab());
  });

  public readonly showRoleDialog = signal(false);

  // Relation role dialog bindings (read during the change detection triggered
  // by toggling the showRoleDialog signal).
  public dialogMode: CmdbMode = CmdbMode.Create;
  public chosenRelation: ExtendedRelation | null = null;
  public chosenRole: ObjectRelationRole | null = null;
  public roleParentTypeIDs: number[] = [];
  public roleChildTypeIDs: number[] = [];
  public selectedInstance: any = null;

  private pendingFocus: RelationFocus | null = null;
  private readonly destroy$ = new Subject<void>();

  private readonly objectRelationService = inject(ObjectRelationService);
  private readonly relationService = inject(RelationService);
  private readonly toastService = inject(ToastService);
  private readonly loaderService = inject(LoaderService);
  private readonly modalService = inject(NgbModal);

  public readonly isLoading$ = this.loaderService.isLoading$;

  /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['objectId']) {
      this.activeKey.set(ATTRIBUTES_KEY);
      this.reloadTabs();
    }
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  /* --------------------------------------------------- EVENTS --------------------------------------------------- */

  public tabKey(tab: ObjectRelationTab): string {
    return objectRelationTabKey(tab);
  }

  public selectTab(key: string): void {
    this.activeKey.set(key);
  }

  public openSelectModal(): void {
    const modalRef = this.modalService.open(ObjectRelationSelectModalComponent, {
      size: 'lg',
      scrollable: true,
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    modalRef.componentInstance.typeId = this.typeId();
    modalRef.componentInstance.existingTabs = this.tabs();

    modalRef.result.then(
      (selection: RelationSelection) => this.onRelationSelected(selection),
      () => { }
    );
  }

  public onRelationSelected(selection: RelationSelection): void {
    const { relation, role } = selection;

    this.chosenRelation = relation;
    this.chosenRole = role;
    this.roleParentTypeIDs = role === 'parent' ? [] : (relation.parent_type_ids || []);
    this.roleChildTypeIDs = role === 'child' ? [] : (relation.child_type_ids || []);
    this.selectedInstance = null;
    this.dialogMode = CmdbMode.Create;
    this.pendingFocus = { relationId: relation.public_id, role };
    this.showRoleDialog.set(true);
  }

  public onAddForTab(tab: ObjectRelationTab): void {
    this.openRoleDialog(tab, CmdbMode.Create, null);
  }

  public onViewRow(tab: ObjectRelationTab, row: ObjectRelationRow): void {
    this.openRoleDialog(tab, CmdbMode.View, row);
  }

  public onEditRow(tab: ObjectRelationTab, row: ObjectRelationRow): void {
    this.openRoleDialog(tab, CmdbMode.Edit, row);
  }

  public onCopyRow(tab: ObjectRelationTab, row: ObjectRelationRow): void {
    this.openRoleDialog(tab, CmdbMode.Create, row);
  }

  public onDeleteRow(tab: ObjectRelationTab, row: ObjectRelationRow): void {
    const modalRef = this.modalService.open(CoreDeleteConfirmationModalComponent, {
      size: 'lg',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    modalRef.componentInstance.title = 'Delete Object Relation';
    modalRef.componentInstance.item = row;
    modalRef.componentInstance.itemType = 'Object Relation';
    modalRef.componentInstance.itemName = row.public_id;

    modalRef.result.then(
      (result) => {
        if (result !== 'confirmed') {
          return;
        }
        this.loaderService.show();
        this.objectRelationService.deleteObjectRelation(row.public_id)
          .pipe(takeUntil(this.destroy$), finalize(() => this.loaderService.hide()))
          .subscribe({
            next: () => {
              this.toastService.success('Relation instance deleted successfully');
              this.reloadTabs({ relationId: tab.relation_id, role: tab.role });
            },
            error: (err) => this.toastService.error(err?.error?.message)
          });
      },
      () => { }
    );
  }

  public onDeleteSelected(tab: ObjectRelationTab, rows: ObjectRelationRow[]): void {
    const targetIDs = (rows || []).map((row) => row.public_id);
    if (!targetIDs.length) {
      return;
    }

    const modalRef = this.modalService.open(CoreDeleteConfirmationModalComponent, {
      size: 'lg',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    modalRef.componentInstance.title = 'Delete Object Relations';
    modalRef.componentInstance.item = rows;
    modalRef.componentInstance.itemType = 'Object Relations';
    modalRef.componentInstance.itemName = `${targetIDs.length} selected relation${targetIDs.length > 1 ? 's' : ''}`;

    modalRef.result.then(
      (result) => {
        if (result !== 'confirmed') {
          return;
        }
        this.loaderService.show();
        this.objectRelationService.deleteManyObjectRelations(targetIDs)
          .pipe(takeUntil(this.destroy$), finalize(() => this.loaderService.hide()))
          .subscribe({
            next: () => {
              this.toastService.success(`${targetIDs.length} relation instance(s) deleted successfully`);
              this.reloadTabs({ relationId: tab.relation_id, role: tab.role });
            },
            error: (err) => this.toastService.error(err?.error?.message)
          });
      },
      () => { }
    );
  }

  public onRoleDialogConfirm(): void {
    this.showRoleDialog.set(false);
    const focus = this.pendingFocus;
    this.pendingFocus = null;
    this.selectedInstance = null;
    this.reloadTabs(focus);
  }

  public onRoleDialogCancel(): void {
    this.showRoleDialog.set(false);
    this.pendingFocus = null;
    this.selectedInstance = null;
  }

  /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  private isHostTab(key: string): boolean {
    return this.hostTabs().some((tab) => tab.key() === key);
  }

  /**
   * Opens the role dialog for an existing tab. Only the relation definition is
   * fetched on demand; parent/child ids are reconstructed from the role and the
   * already-resolved counterpart, so no extra instance fetch is required.
   */
  private openRoleDialog(tab: ObjectRelationTab, mode: CmdbMode, row: ObjectRelationRow | null): void {
    this.loaderService.show();
    this.relationService.getRelation(tab.relation_id)
      .pipe(takeUntil(this.destroy$), finalize(() => this.loaderService.hide()))
      .subscribe({
        next: (definition) => {
          if (!definition) {
            this.toastService.error('Relation definition is missing.');
            return;
          }
          const isParent = tab.role === 'parent';
          this.chosenRelation = { ...definition, canBeParent: isParent, canBeChild: !isParent };
          this.chosenRole = tab.role;
          this.roleParentTypeIDs = tab.role === 'parent' ? [] : (definition.parent_type_ids || []);
          this.roleChildTypeIDs = tab.role === 'child' ? [] : (definition.child_type_ids || []);
          this.selectedInstance = row ? this.buildInstance(row, tab) : null;
          this.dialogMode = mode;
          this.pendingFocus = { relationId: tab.relation_id, role: tab.role };
          this.showRoleDialog.set(true);
        },
        error: (err) => this.toastService.error(err?.error?.message)
      });
  }

  /**
   * Rebuilds the shape the role dialog expects from a slim tab row. The current
   * object sits on the tab's role side; the counterpart is the opposite side.
   */
  private buildInstance(row: ObjectRelationRow, tab: ObjectRelationTab) {
    const isParent = tab.role === 'parent';
    return {
      public_id: row.public_id,
      relation_id: row.relation_id,
      relation_parent_id: isParent ? this.objectId() : row.counterpart.object_id,
      relation_child_id: isParent ? row.counterpart.object_id : this.objectId(),
      field_values: row.field_values
    };
  }

  private reloadTabs(focus?: RelationFocus | null): void {
    const objectId = this.objectId();
    if (!objectId) {
      return;
    }

    this.loaderService.show();
    this.objectRelationService.getRelationTabs(objectId)
      .pipe(takeUntil(this.destroy$), finalize(() => this.loaderService.hide()))
      .subscribe({
        next: (tabs) => {
          this.tabs.set(tabs);

          if (focus) {
            const focusKey = objectRelationTabKey({ relation_id: focus.relationId, role: focus.role });
            if (tabs.some((tab) => objectRelationTabKey(tab) === focusKey)) {
              this.activeKey.set(focusKey);
              return;
            }
          }

          const activeKey = this.activeKey();
          const isProjectedTab = activeKey === ATTRIBUTES_KEY || this.isHostTab(activeKey);
          if (!isProjectedTab && !tabs.some((tab) => objectRelationTabKey(tab) === activeKey)) {
            this.activeKey.set(ATTRIBUTES_KEY);
          }
        },
        error: (err) => this.toastService.error(err?.error?.message)
      });
  }
}
