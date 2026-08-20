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


import { Component, inject, ChangeDetectionStrategy, ChangeDetectorRef, HostListener, Input, OnInit } from '@angular/core';
import { FileMetadata } from '../../../components/file-explorer/model/metadata';
import { FileElement } from '../../../components/file-explorer/model/file-element';
import { CollectionParameters } from '../../../../services/models/api-parameter';
import { FileService } from '../../../components/file-explorer/service/file.service';
import { FileSaverService } from 'ngx-filesaver';
import { NgbActiveModal, NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';
import { ToastService } from '../../../toast/toast.service';
import { InfiniteScrollService } from '../../../services/infinite-scroll.service';
import { APIGetMultiResponse } from '../../../../services/models/api-response';
import { FilemanagerModalComponent } from '../filemanager-modal/filemanager-modal.component';
import { LoaderService } from 'src/app/core/services/loader.service';
import { finalize } from 'rxjs';

@Component({
    selector: 'cmdb-attachments-list-modal',
    templateUrl: './attachments-list-modal.component.html',
    styleUrls: ['./attachments-list-modal.component.scss'],
    standalone: false
})
export class AttachmentsListModalComponent implements OnInit {
  private readonly fileService = inject(FileService);
  private readonly fileSaverService = inject(FileSaverService);
  private readonly modalService = inject(NgbModal);
  public readonly activeModal = inject(NgbActiveModal);
  private readonly toast = inject(ToastService);
  private readonly scrollService = inject(InfiniteScrollService);
  private readonly cdr = inject(ChangeDetectorRef);
  private readonly loaderService = inject(LoaderService);

  @Input() metadata: FileMetadata = new FileMetadata();
  public inProcess: boolean = false;
  public attachments: FileElement[] = [];
  public recordsTotal: number = 0;

  private modalRef: NgbModalRef;
  public isLoading$ = this.loaderService.isLoading$;


  /**
   * Detecting scroll direction
   */
  private page: number = 0;
  private lastPage: number;
  private readonly tag: string = 'attachmentListScroll';
  private readonly defaultApiParameter: CollectionParameters = { page: 1, limit: 100, order: 1 };

  /**
   * Checks whether further data should be loaded
   * @param event trigger on scroll
   */
  @HostListener('scroll', ['$event']) onScrollHost(event: Event): void {
    if (this.scrollService.bottomReached(event, this.tag) && this.page <= this.lastPage) {
      this.getFiles(this.scrollService.getCollectionParameters(this.tag), true);
    }
  }

  public ngOnInit(): void {
    this.fileService.getAllFilesList(this.metadata).subscribe((data: APIGetMultiResponse<FileElement>) => {
      this.attachments.push(...data.results);
      this.recordsTotal = this.attachments.length;
      this.updatePagination(data);
    });
  }

  /**
   * Get all attachments as a list
   * As you scroll, new records are added to the attachments.
   * Without the scrolling parameter the attachments are reinitialized
   * @param apiParameters Instance of {@link CollectionParameters}
   * @param onScroll Control if it is a new file upload
   */
  public getFiles(apiParameters?: CollectionParameters, onScroll: boolean = false): void {
    this.loaderService.show();
    this.fileService.getAllFilesList(this.metadata, apiParameters ? apiParameters : this.defaultApiParameter)
    .pipe(
      finalize(() => {
        this.loaderService.hide();
        this.cdr.markForCheck();
      }))
      .subscribe((data: APIGetMultiResponse<FileElement>) => {
        if (onScroll) {
          this.attachments.push(...data.results);
        } else {
          this.attachments = data.results;
        }
        this.recordsTotal = this.attachments.length;
        this.inProcess = false;
        this.updatePagination(data);
      });
  }

  /**
   * Update pagination properties for infinite scrolling.
   * Current page values are retrieved from the response {@link APIGetMultiResponse}
   * @param data response {@link APIGetMultiResponse} from backend
   */
  private updatePagination(data): void {
    this.page = data.pager.page + 1;
    this.lastPage = data.pager.total_pages;
    this.scrollService.setCollectionParameters(this.page, 100, 'filename', 1, this.tag);
  }

  /**
   * Allows to attach existing files from the file manager (DATAGERRY File Explorer)
   * or new files form local File Explorer
   */
  public addAttachments() {
    this.modalRef = this.modalService.open(FilemanagerModalComponent, {
      size: 'xl',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    this.modalRef.componentInstance.localMetadata = this.metadata;
    this.modalRef.result.then(() => {
      setTimeout(() => {
        this.getFiles(this.defaultApiParameter, false);
        this.cdr.markForCheck();
      }, 1000)
    });
  }

  /**
   * Download selected file
   * @param filename current filename
   */
  public downloadFile(filename: string) {
    this.fileService.downloadFile(filename, this.metadata).subscribe((data: any) => {
      this.fileSaverService.save(data.body, filename);
    });
  }

  /**
   * Delete selected file
   * @param fileElement current selected file
   */
  public deleteFile(fileElement: FileElement) {
    this.loaderService.show();
    const { reference, reference_type } = this.metadata;
    const newReference = typeof reference === 'number' ? [reference] : reference;
    const tempReference = fileElement.metadata.reference ? fileElement.metadata.reference : [];
    fileElement.metadata.reference = typeof tempReference === 'number' ?
      [tempReference].concat(newReference) : tempReference.concat(newReference);
    fileElement.metadata.reference_type = reference_type;
    fileElement.metadata.reference = fileElement.metadata.reference.filter(x => x !== reference);

    this.fileService.putFile(fileElement, true).subscribe((resp) => {
      setTimeout(() => {
        this.getFiles(this.defaultApiParameter);
        this.toast.info(`File was successfully solved: ${resp.filename}`);
        this.cdr.markForCheck();
        this.loaderService.hide();
      }, 1000)
    });
  }
}
