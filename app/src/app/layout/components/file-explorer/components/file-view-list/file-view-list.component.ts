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

import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges } from '@angular/core';
import { FileElement, SelectedFileArray } from '../../model/file-element';
import { BehaviorSubject } from 'rxjs';
import { FileService } from '../../service/file.service';
import { FileSaverService } from 'ngx-filesaver';
import { RenameDialogComponent } from '../../modal/rename-dialog/rename-dialog.component';
import { NgbModal, NgbModalConfig } from '@ng-bootstrap/ng-bootstrap';
import { MoveDialogComponent } from '../../modal/move-dialog/move-dialog.component';
import { CollectionParameters } from '../../../../../services/models/api-parameter';


@Component({
    selector: 'cmdb-file-view-list',
    templateUrl: './file-view-list.component.html',
    styleUrls: ['./file-view-list.component.scss'],
    standalone: false
})
export class FileViewListComponent implements OnChanges {

  @Output() loadFileElementEvent = new EventEmitter<any>();

  /**
   * When setting the overview control,
   * the preselection is reset
   */
  private viewControl: boolean = true;
  @Input()
  public set listView(value: boolean) {
    if (this.selectedFiles && this.selectedFiles.files.length > 0) {
      this.removeSelects();
    }
    this.viewControl = value;
  }

  public get listView(): boolean {
    return this.viewControl;
  }

  private elementFiles: FileElement[] = [];
  @Input()
  set fileElements(value: FileElement[]) {
    this.elementFiles = value;
  }

  get fileElements(): FileElement[] {
    return this.elementFiles;
  }

  private filesSelected: SelectedFileArray;
  @Input()
  set selectedFiles(value: SelectedFileArray) {
    this.filesSelected = value;
  }

  get selectedFiles(): SelectedFileArray {
    return this.filesSelected;
  }

  constructor(public fileService: FileService, private fileSaverService: FileSaverService,
    private modalService: NgbModal, private config: NgbModalConfig) {
    config.backdrop = 'static';
    config.keyboard = false;
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (!changes.hasOwnProperty('listView')) {
      this.listView = true;
    }
  }

  public onSelect(value: FileElement, event?: Event): void {
    const array = this.selectedFiles.files.filter(x => x.public_id === value.public_id);
    if (array.length === 0) {
      this.selectedFiles.files.push(value);
      this.selectedFiles.totalSize = this.selectedFiles.totalSize + value.size;
      if (event) { (event.target as HTMLElement).classList.add('active'); }
    } else {
      this.selectedFiles.files = this.selectedFiles.files.filter(x => x.public_id !== value.public_id);
      this.selectedFiles.totalSize = this.selectedFiles.totalSize - value.size;
      if (event) { (event.target as HTMLElement).classList.remove('active'); }
    }
  }

  public removeSelects(): void {
    const inputElements: any = $('input[class="selected-file"]:checked');
    for (const input of inputElements) {
      input.checked = false;
    }
    this.selectedFiles.files.length = 0;
    this.selectedFiles.totalSize = 0;
  }

  /**
   * Removes unnecessary selections and checks if further selected files exist.
   * If no further selections exist, the checkbox 'Select all' will be deactivated.
   * @param value selected FileElement
   */
  private updateSelectedFileList(value: FileElement): void {
    this.selectedFiles.files = this.selectedFiles.files.filter(x => x.public_id !== value.public_id);
    const inputElements: any = $('input[class="selected-file"]:checked');
    inputElements.length > 0 ? inputElements.checked = true : inputElements.checked = false;
  }

  public downloadFile(value: FileElement) {
    const { filename, metadata } = value;
    this.fileService.downloadFile(filename, metadata).subscribe((data: any) => {
      this.fileSaverService.save(data.body, filename);
    });
  }

  public renameFile(value: any) {
    const folderModal = this.modalService.open(RenameDialogComponent, {
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    folderModal.componentInstance.selectedFileFolder = new BehaviorSubject<any>(value);
    folderModal.result.then((result) => {
      if (result) {
        const fileElement = value;
        fileElement.filename = result.filename;
        this.postFileChanges(fileElement);
      }
    });
  }

  public moveFile(value: FileElement) {
    const folderModal = this.modalService.open(MoveDialogComponent, {
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    this.updateSelectedFileList(value);
    folderModal.result.then((result) => {
      if (result) {
        const fileElement = value;
        fileElement.filename = value.filename;
        fileElement.metadata.parent = result.parent;
        this.postFileChanges(fileElement);
      }
    });
  }

  /**
 * Deletes a file from the list and updates the UI optimistically.
 * @param value - The file element to be deleted.
  */
  public deleteFile(value: FileElement) {

    this.elementFiles = this.elementFiles.filter(file => file.public_id !== value.public_id);
    this.updateSelectedFileList(value);

    this.fileService.deleteFile(value.public_id, {}).subscribe({
      next: () => {
        this.loadFolderFiles();
      },
      error: (err) => {
        this.elementFiles.push(value);
        this.loadFolderFiles();
      }
    });
  }


  private postFileChanges(curr: any): void {
    this.fileService.putFile(curr).subscribe(() => {
      this.loadFolderFiles();
    });
  }

  public loadFolderFiles(value?: CollectionParameters) {
    this.loadFileElementEvent.emit(value);
  }
}
