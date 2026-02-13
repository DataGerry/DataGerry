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
   * Possible dnd effect
   */
  public effect: DropEffect = 'move';

  /**
   * Tree change emitter
   */
  @Output() public change: EventEmitter<{ type: string, value: any }>;

  /**
   * Constructor of CategoryTreeComponent
   */
  public constructor() {
    this.change = new EventEmitter<{ type: string, value: any }>();
  }

  /**
   * When drag event started
   * @param item CmdbCategoryNode node element
   * @param tree parent root CmdbCategoryTree of node
   * @param effect drag n drop effect
   */
  public onDragged(item: CmdbCategoryNode, tree: CmdbCategoryTree, effect: DropEffect) {
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
  public onDrop(event: DndDropEvent, tree?: CmdbCategoryTree) {
    let index = event.index;
    if (typeof index === 'undefined') {
      index = tree.length;
    }
    tree.splice(index, 0, event.data);
    this.updateTree(tree);
  }

  /**
   * Updates the order of the tree based on its index
   * @param tree root element of the node
   */
  public updateTree(tree: CmdbCategoryTree) {
    for (let i = 0; i < tree.length; i++) {
      const node = tree[i];
      node.category.meta.order = i;
    }
    return tree;
  }
}
