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

import { Component, EventEmitter, Input, OnDestroy, Output } from '@angular/core';
import { CmdbCategory, CmdbCategoryNode } from '../../../models/cmdb-category';
import { CmdbMode } from '../../../modes.enum';
import { NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';
import { CategoryService } from '../../../services/category.service';
import { Router } from '@angular/router';
import { DeleteCategoryModalComponent } from '../modals/delete-category-modal/delete-category-modal.component';
import { ReplaySubject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

@Component({
    selector: 'cmdb-category-node',
    templateUrl: './category-node.component.html',
    styleUrls: ['./category-node.component.scss'],
    standalone: false
})
export class CategoryNodeComponent implements OnDestroy {

  /**
   * Edit mode of tree
   */
  @Input() public mode: CmdbMode = CmdbMode.View;

  /**
   * Current node element
   */
  @Input() public node: CmdbCategoryNode;

  /**
   * Whether the children of this node are hidden
   */
  @Input() public collapsed: boolean = false;

  /**
   * Whether this category can become a child of the row above it.
   */
  @Input() public canIndent: boolean = false;

  /**
   * Whether this category can be moved one level out again.
   */
  @Input() public canOutdent: boolean = false;

  /**
   * Tooltips naming the target of the nesting controls.
   */
  @Input() public indentHint: string = '';
  @Input() public outdentHint: string = '';

  /**
   * Nesting requests for this category.
   */
  @Output() public indent: EventEmitter<void> = new EventEmitter<void>();
  @Output() public outdent: EventEmitter<void> = new EventEmitter<void>();

  /**
   * Node change emitter
   */
  @Output() public change: EventEmitter<{ type: string, value: any }> = new EventEmitter<{ type: string, value: any }>();

  /**
   * Request to show or hide the children of this node
   */
  @Output() public toggle: EventEmitter<void> = new EventEmitter<void>();

  /**
   * Global unsubscriber for http calls to the rest backend.
   */
  private unSubscribe: ReplaySubject<void> = new ReplaySubject();

  private deleteRef: NgbModalRef;

  public constructor(private deleteModal: NgbModal, private router: Router, private categoryService: CategoryService) {
  }

  public get isOrganizing(): boolean {
    return this.mode === CmdbMode.Edit;
  }

  public get hasChildren(): boolean {
    return this.node?.children?.length > 0;
  }

  public get iconClass(): string {
    return this.node?.category?.meta?.icon || 'far fa-folder-open';
  }

  public get toggleLabel(): string {
    const action = this.collapsed ? 'Expand' : 'Collapse';
    return `${action} ${this.node?.category?.label}`;
  }

  /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

  public ngOnDestroy(): void {
    this.unSubscribe?.next();
    this.unSubscribe?.complete();
  }

  /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

  public onToggle(): void {
    this.toggle.emit();
  }

  public onEdit(): void {
    this.router.navigate(['/', 'framework', 'category', 'edit', this.node.category.public_id]);
  }

  public onDelete(category: CmdbCategory): void {
    this.deleteRef = this.deleteModal.open(DeleteCategoryModalComponent, {
      size: 'lg',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    this.deleteRef.componentInstance.category = category;
    this.deleteRef.result.then((result) => {
      if (result === 'delete') {
        this.categoryService.deleteCategory(category.public_id).pipe(takeUntil(this.unSubscribe))
          .subscribe(() => {
            this.change.emit();
          });
      }
    }, () => undefined);
  }
}
