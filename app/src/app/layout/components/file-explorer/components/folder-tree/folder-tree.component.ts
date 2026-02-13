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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { Component, EventEmitter, Input, OnChanges, OnInit, Output, SimpleChanges } from '@angular/core';
import { FileElement } from '../../model/file-element';
import { FileMetadata } from '../../model/metadata';
import { BehaviorSubject } from 'rxjs';

@Component({
    selector: 'cmdb-folder-tree',
    templateUrl: './folder-tree.component.html',
    styleUrls: ['./folder-tree.component.scss'],
    standalone: false
})
export class FolderTreeComponent implements OnInit, OnChanges {

  private elementFileTree: FileElement[] = [];
  private metadata: FileMetadata = new FileMetadata();
  private selectedFileElement: any;

  @Input()
  set fileTree(value: FileElement[]) {
    this.elementFileTree = value;
  }

  get fileTree(): FileElement[] {
    return this.elementFileTree;
  }

  @Input()
  set selectedFileFolder( value: BehaviorSubject<FileElement>) {
    this.selectedFileElement = value;
  }

  get selectedFileFolder(): BehaviorSubject<FileElement> {
    return this.selectedFileElement;
  }

  /**
   * Marks a property in a child component as a
   * doorway through which data can travel from the child to the parent.
   */
  @Output() createFileElementEvent = new EventEmitter<any>();
  @Output() renameFileElementEvent = new EventEmitter<any>();
  @Output() moveFileElementEvent = new EventEmitter<any>();
  @Output() deleteFileElementEvent = new EventEmitter<any>();
  @Output() loadFileElementEvent = new EventEmitter<any>();

  constructor() { }

  static createFolderTree(arr): any[] {
    const tree = [];
    const mappedArr = {};
    let arrElem;
    let mappedElem;

    // First map the nodes of the array to an object -> create a hash table.
    for (let i = 0, len = arr.length; i < len; i++) {
      arrElem = arr[i];
      mappedArr[arrElem.public_id] = arrElem;
      mappedArr[arrElem.public_id].children = [];
    }

    for (const id in mappedArr) {
      if (mappedArr.hasOwnProperty(id)) {
        mappedElem = mappedArr[id];
        // If the element is not at the root level, add it to its parent array of children.
        if (mappedElem.metadata.parent) {
          mappedArr[mappedElem.metadata.parent].children.push(mappedElem);
        } else {
          tree.push(mappedElem);
        }
      }
    }
    return [{filename: '', public_id: null, hasSubFolders: true, children: tree, metadata: { parent: null } }];
  }

  ngOnInit(): void {
    this.fileTree = FolderTreeComponent.createFolderTree(this.fileTree);
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes.fileTree) {
      this.fileTree = FolderTreeComponent.createFolderTree(changes.fileTree.currentValue);
    }
  }

  public dropTree(event, value): void {
    if (value.children && value.children.length > 0) {
      this.selectedFileFolder.next(value);
      value.hasSubFolders = !value.hasSubFolders;
      event.stopPropagation();
    }
  }

  public loadFolderFiles(value: FileElement) {
    this.selectedFileFolder.next(value);
    this.loadFileElementEvent.emit();
  }

  public createFolder(): void {
    this.createFileElementEvent.emit();
  }

  public renameFolder(): void {
    this.renameFileElementEvent.emit();
  }

  public moveFolder() {
    this.moveFileElementEvent.emit();
  }

  public deleteFolder(value: FileElement): void {
    this.deleteFileElementEvent.emit(value);
  }

  public loadContextMenu() {
  }
}
