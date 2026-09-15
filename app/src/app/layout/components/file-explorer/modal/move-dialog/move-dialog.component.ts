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

import {Component, inject, OnInit} from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { FileMetadata } from '../../model/metadata';
import { FileService } from '../../service/file.service';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { FileElement } from '../../model/file-element';
import { APIGetMultiResponse } from '../../../../../services/models/api-response';
import {CollectionParameters} from "../../../../../services/models/api-parameter";

// The scrolling modal body would clip an inline dropdown.
const DROPDOWN_HOST = '.dg-modal-window';


@Component({
    selector: 'cmdb-move-dialog',
    templateUrl: './move-dialog.component.html',
    styleUrls: ['./move-dialog.component.scss'],
    standalone: false
})
export class MoveDialogComponent implements OnInit {

  public basicForm: UntypedFormGroup;
  public destinationFolder: FileElement[] = [];
  public readonly DROPDOWN_HOST = DROPDOWN_HOST;
  private readonly defaultApiParameter: CollectionParameters = {page: 1, limit: 100, order: 1};

  private readonly fileService = inject(FileService);
  public readonly activeModal = inject(NgbActiveModal);

  groupByFn = (item) => item.metadata.parent ? item.metadata.parent : 0;

  groupValueFn = (_: string, children: any[]) => (
    {
      parentName: this.findParentName(children[0].metadata.parent),
      total: children.length,
      public_id: children[0].metadata.parent
    })

  private findParentName(publicID: number) {
    return publicID === null ? 'Without Parent' : this.destinationFolder.filter(x => x.public_id === publicID)[0].filename;
  }

  public ngOnInit(): void {
    this.basicForm = new UntypedFormGroup({
      folder: new UntypedFormControl(null, Validators.required)
    });

    this.fileService.getAllFilesList(new FileMetadata({folder: true}), this.defaultApiParameter)
      .subscribe( (data: APIGetMultiResponse<FileElement>) => {
        this.destinationFolder = data.results;
    });
  }
}
