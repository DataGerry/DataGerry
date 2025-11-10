/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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

import { ChangeDetectorRef, Component, OnDestroy, OnInit } from '@angular/core';
import { FileSaverService } from 'ngx-filesaver';
import { ActivatedRoute } from '@angular/router';
import { NgbModal, NgbModalConfig, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';
import { APIGetMultiResponse } from '../../../../services/models/api-response';
import { FileMetadata } from '../../../../layout/components/file-explorer/model/metadata';
import { FileService } from '../../../../layout/components/file-explorer/service/file.service';
import { FileElement } from '../../../../layout/components/file-explorer/model/file-element';
import { AttachmentsListModalComponent } from '../../../../layout/helpers/modals/attachments-list-modal/attachments-list-modal.component';

@Component({
    selector: 'cmdb-object-attachments',
    templateUrl: './object-attachments.component.html',
    styleUrls: ['./object-attachments.component.scss'],
    standalone: false
})
export class ObjectAttachmentsComponent implements OnInit, OnDestroy {

  public attachments: FileElement[] = [];
  public attachmentsTotal: number = 0;
  private metadata: FileMetadata = new FileMetadata();
  private modalRef: NgbModalRef;

  constructor(private fileService: FileService, private fileSaverService: FileSaverService,
              private route: ActivatedRoute, private modalService: NgbModal, private config: NgbModalConfig, private cdr: ChangeDetectorRef) {
    this.route.params.subscribe((params) => {
      this.metadata.reference = Number(params.publicID);
      this.metadata.reference_type = 'object';
    });
    config.backdrop = 'static';
    config.keyboard = false;
  }


  public ngOnInit(): void {
    this.fetchAttachments()
  }


  public ngOnDestroy(): void {
    if (this.modalRef) {
      this.modalRef.close();
    }
  }


  public showAttachments(): void {
    this.modalRef = this.modalService.open(AttachmentsListModalComponent);
    this.modalRef.componentInstance.metadata = this.metadata;
  
    // Whether closed with Done/x (resolve) or Close button (reject), always re-fetch
    this.modalRef.result
      .then(() => this.fetchAttachments())
      .catch(() => this.fetchAttachments());
  }
  


  private fetchAttachments(): void {
    this.fileService.getAllFilesList(this.metadata).subscribe((resp: APIGetMultiResponse<FileElement>) => {
      this.attachments = resp.results;
      this.attachmentsTotal = this.attachments.length;
      this.cdr.markForCheck();
    });
  }

}
