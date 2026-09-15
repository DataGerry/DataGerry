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
  Input,
  OnDestroy,
  OnInit,
  inject,
  signal
} from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { Subject, finalize, takeUntil } from 'rxjs';

import { RelationService } from 'src/app/framework/services/relaion.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { CmdbRelation } from 'src/app/framework/models/relation.model';
import { ExtendedRelation } from 'src/app/framework/models/object.model';
import { ObjectRelationRole, ObjectRelationTab } from 'src/app/framework/models/object-relation.model';

interface RelationSelection {
  relation: ExtendedRelation;
  role: ObjectRelationRole;
}

/**
 * Modal that lets the user pick which relation (and role) to create for the
 * current object. Relation/role combinations already present as tabs are
 * disabled so the same relation is not created twice for the same role.
 */
@Component({
  selector: 'cmdb-object-relation-select-modal',
  templateUrl: './object-relation-select-modal.component.html',
  styleUrls: ['./object-relation-select-modal.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  standalone: false
})
export class ObjectRelationSelectModalComponent implements OnInit, OnDestroy {

  /* --------------------------------------------------- INPUTS --------------------------------------------------- */

  @Input() public typeId: number;
  @Input() public existingTabs: ObjectRelationTab[] = [];

  /* --------------------------------------------------- PUBLIC STATE --------------------------------------------------- */

  public readonly relations = signal<ExtendedRelation[]>([]);
  public readonly loading = signal(false);
  public readonly chosen = signal<RelationSelection | null>(null);

  public readonly activeModal = inject(NgbActiveModal);

  private readonly destroy$ = new Subject<void>();
  private readonly relationService = inject(RelationService);
  private readonly toastService = inject(ToastService);

  /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

  ngOnInit(): void {
    this.loadAvailableRelations();
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  /* --------------------------------------------------- EVENTS --------------------------------------------------- */

  public onSelect(relation: ExtendedRelation, role: ObjectRelationRole): void {
    if ((role === 'parent' && !relation.canBeParent) || (role === 'child' && !relation.canBeChild)) {
      return;
    }
    this.chosen.set({ relation, role });
  }

  public isChosen(relation: ExtendedRelation, role: ObjectRelationRole): boolean {
    const chosen = this.chosen();
    return chosen?.relation === relation && chosen?.role === role;
  }

  public onConfirm(): void {
    const chosen = this.chosen();
    if (chosen) {
      this.activeModal.close(chosen);
    }
  }

  public onCancel(): void {
    this.activeModal.dismiss('cancel');
  }

  /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  private loadAvailableRelations(): void {
    const typeId = this.typeId;
    if (!typeId) {
      this.toastService.warning('No valid type ID found.');
      return;
    }

    this.loading.set(true);

    const params = {
      filter: {
        $or: [
          { parent_type_ids: { $in: [typeId] } },
          { child_type_ids: { $in: [typeId] } }
        ]
      },
      limit: 0,
      sort: '',
      order: 1,
      page: 1
    };

    this.relationService.getRelations(params)
      .pipe(takeUntil(this.destroy$), finalize(() => this.loading.set(false)))
      .subscribe({
        next: (response) => this.relations.set(this.buildExtendedRelations(response?.results || [], typeId)),
        error: (err) => this.toastService.error(err?.error?.message)
      });
  }

  private buildExtendedRelations(relations: CmdbRelation[], typeId: number): ExtendedRelation[] {
    return relations
      .map((relation) => {
        const canBeParent = !!relation.parent_type_ids?.includes(typeId) && !this.isRoleUsed(relation.public_id, 'parent');
        const canBeChild = !!relation.child_type_ids?.includes(typeId) && !this.isRoleUsed(relation.public_id, 'child');
        return { ...relation, canBeParent, canBeChild };
      })
      .filter((relation) => relation.canBeParent || relation.canBeChild);
  }

  private isRoleUsed(relationId: number, role: ObjectRelationRole): boolean {
    return this.existingTabs.some((tab) => tab.relation_id === relationId && tab.role === role);
  }
}
