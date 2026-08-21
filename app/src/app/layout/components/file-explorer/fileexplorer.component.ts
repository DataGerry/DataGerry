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

import { Component, HostListener, Input, OnDestroy, OnInit } from '@angular/core';
import { FileService } from './service/file.service';
import { NgbModal, NgbModalConfig, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';
import { NewFolderDialogComponent } from './modal/new-folder-dialog/new-folder-dialog.component';
import { BehaviorSubject, finalize } from 'rxjs';
import { FileElement, SelectedFileArray} from './model/file-element';
import { FileMetadata } from './model/metadata';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { InfiniteScrollService } from '../../services/infinite-scroll.service';
import { ToastService } from '../../toast/toast.service';
import { CollectionParameters } from '../../../services/models/api-parameter';
import { APIGetMultiResponse } from '../../../services/models/api-response';
import { AddAttachmentsModalComponent } from '../../helpers/modals/add-attachments-modal/add-attachments-modal.component';
import { RenameDialogComponent } from './modal/rename-dialog/rename-dialog.component';
import { MoveDialogComponent } from './modal/move-dialog/move-dialog.component';
import { GeneralModalComponent } from '../../helpers/modals/general-modal/general-modal.component';
import { MetadataInfoComponent } from './modal/metadata-info/metadata-info.component';
import { LoaderService } from '../../../core/services/loader.service';

@Component({
    selector: 'cmdb-fileexplorer',
    templateUrl: './fileexplorer.component.html',
    styleUrls: ['./fileexplorer.component.scss'],
    standalone: false
})
export class FileExplorerComponent implements OnInit, OnDestroy {

  constructor(private fileService: FileService, private modalService: NgbModal, private config: NgbModalConfig,
              private scrollService: InfiniteScrollService, private toast: ToastService, private loaderService: LoaderService) {
    config.backdrop = 'static';
    config.keyboard = false;
  }

  /**
   * Transferred Metadata will be merged.
   * Default values can be overwritten, if these are passed
   */
  private defaultMetadata = new FileMetadata({folder: false});
  @Input()
  public set localMetadata(value: FileMetadata) {
    this.defaultMetadata = Object.assign({}, this.defaultMetadata, value);
  }

  public get localMetadata(): FileMetadata {
    return this.defaultMetadata;
  }

  private fileSeletedElements: SelectedFileArray = {files: [], totalSize: 0};
  @Input()
  public set selectedFileElements(value: SelectedFileArray) {
    this.fileSeletedElements = value;
  }

  public get selectedFileElements(): SelectedFileArray {
    return this.fileSeletedElements;
  }

  /**
   * FormController
   */
  public searchForm: UntypedFormGroup = new UntypedFormGroup({
    search: new UntypedFormControl('', Validators.required)
  });

  /**
   * Data sharing between components
   */
  public fileElements: FileElement[] = [];
  public fileTree: FileElement[] = [];
  public selectedFolderElement = new BehaviorSubject<any>(null);
  public recordsTotal: number = 0;

  /**
   * Controls the file view.
   * Default is always true and display is switched to list overview
   */
  public listView: boolean = true;

  /**
   * Metadata for filtering Files from Database
   */
  private apiViewListParameter: CollectionParameters = {page: 1, limit: 100, sort: 'filename', order: -1};
  private apiTreeListParameter: CollectionParameters = {page: 1, limit: 100, sort: 'filename', order: -1};
  private modalRef: NgbModalRef;

  /**
   * Detecting scroll direction for file list
   */
  private page: number;
  private lastPage: number;
  private readonly viewListScroll: string = 'viewFilesScroll';

  /**
   * Detecting scroll direction for tree list
   */
  private pageTree: number;
  private lastPageTree: number;
  private readonly treeListScroll: string = 'treeFolderScroll';

  public isLoading$ = this.loaderService.isLoading$;

  @HostListener('scroll', ['$event']) onScrollListViewHost(e: Event): void {
    if (this.scrollService.bottomReached(e, this.viewListScroll) && this.page <= this.lastPage) {
      this.loadFiles(this.scrollService.getCollectionParameters(this.viewListScroll), true);
    }
  }

  @HostListener('scroll', ['$event']) onScrollTreeListHost(e: Event): void {
    if (this.scrollService.bottomReached(e, this.treeListScroll) && this.pageTree <= this.lastPageTree) {
      this.loadFileTree(this.scrollService.getCollectionParameters(this.treeListScroll), true);
    }
  }

  ngOnInit() {
    this.searchForm.valueChanges.subscribe(value => {
      if (value !== '') {
        const SEARCH = 'searchTerm';
        this.apiViewListParameter[SEARCH] = value.search;
        this.loadFiles(this.apiViewListParameter);
      }
    });
    this.loadFiles(this.apiViewListParameter);
    this.loadFileTree(this.apiTreeListParameter);
  }

  /**
   * Get all attachments as a list
   * As you scroll, new records are added to the attachments.
   * Without the scrolling parameter the attachments are reinitialized
   * @param apiParameters Instance of {@link CollectionParameters}
   * @param onScroll Control if it is a new file upload
   */
  public loadFiles(apiParameters?: CollectionParameters, onScroll: boolean = false): void {
    this.loaderService.show();
    const metadata = this.generateMetadata();
    apiParameters = apiParameters ? apiParameters : this.apiViewListParameter;
    this.fileService.getAllFilesList(metadata, apiParameters).pipe(finalize(() => this.loaderService.hide()))
      .subscribe((data: APIGetMultiResponse<any>) => {
        if (onScroll) {
          this.fileElements.push(...data.results);
        } else {
          this.fileElements =  data.results;
        }
        this.recordsTotal = data.total;
        this.updatePagination(data, apiParameters.sort, apiParameters.order, this.viewListScroll);
      });
  }

  public loadFileTree(apiParameters?: CollectionParameters, onScroll: boolean = false) {
    this.loaderService.show();
    this.fileService.getAllFilesList(new FileMetadata({folder: true}), apiParameters)
    .pipe(finalize(() => this.loaderService.hide()))
      .subscribe((data: APIGetMultiResponse<any>) => {
        if (onScroll) {
          this.fileTree.push(...data.results);
        } else {
          this.fileTree = data.results;
        }
        this.updatePagination(data, apiParameters.sort, apiParameters.order, this.treeListScroll);
      });
  }

  private updatePagination(data, sort: string = 'filename', order: number = -1, identifier: string) {
    this.page = data.pager.page + 1;
    this.lastPage = data.pager.total_pages;
    this.scrollService.setCollectionParameters(this.page, 100, sort, order, identifier);
  }

  private generateMetadata(folder: boolean = false): FileMetadata {
    const value = this.selectedFolderElement.getValue();
    const {public_id} = value ? value : {public_id: null};
    return new FileMetadata({ parent: public_id, folder });
  }

  public addFolder() {
    this.modalRef = this.modalService.open(NewFolderDialogComponent, {
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    this.modalRef.componentInstance.selectedFileFolder = this.selectedFolderElement;
    this.modalRef.result.then((result) => {
      if (result) {
        this.reorderFolderTree(result.data);
      }
    });
  }

  public showMetadataInfo(value: FileElement) {
    this.modalRef = this.modalService.open(MetadataInfoComponent, {
      size: 'lg',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    this.modalRef.componentInstance.fileElement = value;
    this.modalRef.componentInstance.folderTree = this.fileTree;
    this.modalRef.result.then(() => {});
  }

  private reorderFolderTree(item: FileElement, apiParameter= {page: 1, limit: 100, sort: 'filename', order: -1}) {
    this.loaderService.show();
    this.fileService.getAllFilesList(new FileMetadata({folder: true}), apiParameter)
    .pipe(finalize(() =>   this.loaderService.hide()))
      .subscribe((data: APIGetMultiResponse<any>) => {
      for (const el of data.results) {
        if (el.public_id === item.metadata.parent) {
          el.hasSubFolders = true;
        }
        if (this.fileTree.find(f => f.public_id === el.public_id && f.hasSubFolders)) {
          el.hasSubFolders = true;
        }
      }
      this.fileTree = data.results;
    });
  }

  public uploadFile() {
    const metadata = this.generateMetadata();
    this.modalRef = this.modalService.open(AddAttachmentsModalComponent, {
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    this.modalRef.componentInstance.metadata = metadata;
    this.modalRef.result.then(() => {
      this.loadFiles(this.apiViewListParameter);
    });
  }

  public renameFile(value?: FileElement) {
    if (value) { this.selectedFolderElement.next(value); }
    this.modalRef = this.modalService.open(RenameDialogComponent, {
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    this.modalRef.componentInstance.selectedFileFolder = this.selectedFolderElement;
    this.modalRef.result.then((result) => {
      if (result) {
        this.postFileChanges(result, 'renamed');
      }
    });
  }

  public moveFiles(value: FileElement[]) {
    this.modalRef = this.modalService.open(MoveDialogComponent, {
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    this.modalRef.result.then((result) => {
      if (result) {
        for (const file of value) {
          const fileElement = file;
          fileElement.metadata.parent = result.parent;
          this.fileService.putFile(fileElement).subscribe(() => {
            this.toast.info(`File was successfully moved: ${fileElement.filename}`);
          });
        }
        this.loadFiles(this.apiViewListParameter);
      }
    });
  }
  public moveFile() {
    this.modalRef = this.modalService.open(MoveDialogComponent, {
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    this.modalRef.result.then((result) => {
      if (result) {
        this.postFileChanges(result, 'moved');
      }
    });
  }

  public deleteFiles(value: FileElement[]) {
    for (const file of value) {
      this.fileService.deleteFile(file.public_id, {}).subscribe(() => {
        this.loadFiles(this.apiViewListParameter);
      });
    }
  }

  public deleteFile(value: FileElement) {
    this.selectedFolderElement.next(value);
    const metadata = this.generateMetadata();
    this.deleteFileModal(value.filename).then(result => {
      if (result) {
        this.loaderService.show();
        this.fileService.deleteFile(value.public_id, metadata).pipe(finalize(() =>  this.loaderService.hide())).subscribe(() => {
            this.reorderFolderTree(value);
            this.selectedFolderElement = new BehaviorSubject<any>(null);
          }
        );
      }
    });
  }

  private deleteFileModal(filename: string) {
    this.modalRef = this.modalService.open(GeneralModalComponent, {
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    this.modalRef.componentInstance.title = `Delete ${filename}`;
    this.modalRef.componentInstance.modalMessage =
      `Are you sure you want to delete ${filename} Folder?`;
    this.modalRef.componentInstance.subModalMessage =
      `All files associated to this Folder will permanently deleted. This operation can not be undone!`;
    this.modalRef.componentInstance.buttonDeny = 'Cancel';
    this.modalRef.componentInstance.buttonAccept = 'Delete';
    return this.modalRef.result;
  }

  public ngOnDestroy(): void {
    if (this.modalRef) {
      this.modalRef.close();
    }
  }

  /**
   * Post changes and reorder Folder-Tree
   * @param changes file changes
   * @param action renamed or created
   */
  private postFileChanges(changes: any, action: string) {
    this.loaderService.show();
    const fileElement = this.selectedFolderElement.getValue();
    const fileType = fileElement.metadata.folder ? 'Folder' : 'File';
    fileElement.filename = changes.filename !== undefined ? changes.filename : fileElement.filename;
    fileElement.metadata.parent = changes.parent !== undefined ? changes.parent : fileElement.metadata.parent;
    this.fileService.putFile(fileElement).pipe(finalize(() => this.loaderService.hide())).subscribe((resp: FileElement) => {
      this.reorderFolderTree(resp);
      this.toast.info(`${fileType} was successfully ${action}: ${fileElement.filename}`);
    });
  }
}
