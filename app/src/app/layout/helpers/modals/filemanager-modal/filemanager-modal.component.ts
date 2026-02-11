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

import { Component, Input, OnInit } from '@angular/core';
import { FileMetadata } from '../../../components/file-explorer/model/metadata';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { APIGetMultiResponse } from '../../../../services/models/api-response';
import { FileElement, SelectedFileArray } from '../../../components/file-explorer/model/file-element';
import { FileService } from '../../../components/file-explorer/service/file.service';
import { ToastService } from '../../../toast/toast.service';

@Component({
    selector: 'cmdb-filemanager-modal',
    templateUrl: './filemanager-modal.component.html',
    styleUrls: ['./filemanager-modal.component.scss'],
    standalone: false
})
export class FilemanagerModalComponent implements OnInit {

  @Input() localMetadata: FileMetadata = new FileMetadata();
  public selectedFileElements: SelectedFileArray = {files: [], totalSize: 0};
  public recordsTotal: number = 0;

  constructor(public activeModal: NgbActiveModal, private fileService: FileService, private toast: ToastService) {}

  public ngOnInit(): void {
    this.fileService.getAllFilesList(this.localMetadata).subscribe((data: APIGetMultiResponse<FileElement>) => {
      this.recordsTotal = data.total;
    });
  }

  public postFileOnDone() {
    const {reference, reference_type} = this.localMetadata;
    const newReference = typeof reference === 'number' ? [reference] : reference;
    this.selectedFileElements.files.forEach(fileElement => {
      const tempReference = fileElement.metadata.reference ? fileElement.metadata.reference : [];
      fileElement.metadata.reference = typeof tempReference === 'number' ?
        [tempReference].concat(newReference) : tempReference.concat(newReference);
      fileElement.metadata.reference_type = reference_type;
      this.fileService.putFile(fileElement, true).subscribe((resp) => {
        this.toast.info(`File(s) was successfully added: ${resp.filename}`);
      });
    });
    this.activeModal.close(true);
  }
}
