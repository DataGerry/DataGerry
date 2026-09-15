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

import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CmdbCategoryNode, CmdbCategoryTree } from '../../../models/cmdb-category';
import { DndDropEvent, DropEffect } from 'ngx-drag-drop';
import { CmdbMode } from '../../../modes.enum';

@Component({
    selector: 'cmdb-category-tree',
    templateUrl: './category-tree.component.html',
    styleUrls: ['./category-tree.component.scss'],
    standalone: false
})
export class CategoryTreeComponent {

  /**
   * Edit mode of tree
   */
  @Input() public mode: CmdbMode = CmdbMode.View;

  /**
   * Root element of the category tree
   */
  @Input() public tree: CmdbCategoryTree;

  /**
   * Public IDs of the nodes whose children are hidden.
   * The same set instance travels down the recursion so the page can expand or collapse everything at once.
   */
  @Input() public collapsed: Set<number> = new Set<number>();

  /**
   * True for the outermost tree. Its first row has no parent above it, so the connector differs.
   */
  @Input() public root: boolean = false;

  /**
   * Node this sub tree hangs under, and the list that node lives in.
   * Both are needed to move a category one level out again.
   */
  @Input() public parentNode: CmdbCategoryNode;
  @Input() public parentTree: CmdbCategoryTree;

  /**
   * Category currently being dragged. The drop placeholder renders it, so the tree shows the
   * result of the drop before it happens.
   */
  @Input() public draggedNode: CmdbCategoryNode;

  /**
   * Tree change emitter. Fires when a node was removed and the data has to be reloaded.
   */
  @Output() public change: EventEmitter<{ type: string, value: any }> = new EventEmitter<{ type: string, value: any }>();

  /**
   * Fires whenever a drag and drop changed the local order or nesting of the tree.
   */
  @Output() public reorder: EventEmitter<void> = new EventEmitter<void>();

  /**
   * Announces which category a drag started on.
   */
  @Output() public dragStarted: EventEmitter<CmdbCategoryNode> = new EventEmitter<CmdbCategoryNode>();

  public get isOrganizing(): boolean {
    return this.mode === CmdbMode.Edit;
  }

  public get draggedLabel(): string {
    return this.draggedNode?.category?.label ?? 'Move here';
  }

  public get draggedIcon(): string {
    return this.draggedNode?.category?.meta?.icon || 'far fa-folder-open';
  }

  /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

  public onDragStart(node: CmdbCategoryNode): void {
    this.dragStarted.emit(node);
  }

  /**
   * When drag event started
   * @param item CmdbCategoryNode node element
   * @param tree parent root CmdbCategoryTree of node
   * @param effect drag n drop effect
   */
  public onDragged(item: CmdbCategoryNode, tree: CmdbCategoryTree, effect: DropEffect): void {
    if (effect === 'move') {
      const index = tree.indexOf(item);
      tree.splice(index, 1);
    }
  }

  /**
   * Function which is called when event drop
   * @param event data category node
   * @param tree selected node
   */
  public onDrop(event: DndDropEvent, tree?: CmdbCategoryTree): void {
    let index = event.index;
    if (typeof index === 'undefined') {
      index = tree.length;
    }
    tree.splice(index, 0, event.data);
    this.updateTree(tree);
    this.reorder.emit();
  }

  /**
   * Nesting by drag and drop means hitting a thin strip, so nesting also has explicit controls:
   * a category becomes a child of the row above it.
   */
  public onIndent(node: CmdbCategoryNode, index: number): void {
    const newParent = this.tree[index - 1];

    if (!newParent) {
      return;
    }

    this.tree.splice(index, 1);
    newParent.children = newParent.children ?? ([] as CmdbCategoryTree);
    newParent.children.push(node);
    this.collapsed.delete(newParent.category.public_id);
    this.reorder.emit();
  }

  /**
   * Moves a category one level up, directly behind its former parent.
   */
  public onOutdent(node: CmdbCategoryNode, index: number): void {
    const parentIndex = this.parentTree?.indexOf(this.parentNode);

    if (parentIndex === undefined || parentIndex === -1) {
      return;
    }

    this.tree.splice(index, 1);
    this.parentTree.splice(parentIndex + 1, 0, node);
    this.reorder.emit();
  }

  public onToggle(node: CmdbCategoryNode): void {
    const publicID = node.category.public_id;

    if (this.collapsed.has(publicID)) {
      this.collapsed.delete(publicID);
    } else {
      this.collapsed.add(publicID);
    }
  }

  /* --------------------------------------------------- FUNCTIONS ---------------------------------------------------- */

  public isCollapsed(node: CmdbCategoryNode): boolean {
    return this.collapsed.has(node.category.public_id);
  }

  public indentHint(index: number): string {
    const newParent = this.tree[index - 1];

    return newParent ? `Nest under ${newParent.category.label}` : 'Nothing above to nest under';
  }

  public outdentHint(): string {
    return this.parentNode ? `Move out of ${this.parentNode.category.label}` : 'Already at the top level';
  }

  /**
   * Updates the order of the tree based on its index
   * @param tree root element of the node
   */
  public updateTree(tree: CmdbCategoryTree): CmdbCategoryTree {
    for (let i = 0; i < tree.length; i++) {
      const node = tree[i];
      node.category.meta.order = i;
    }

    return tree;
  }
}
