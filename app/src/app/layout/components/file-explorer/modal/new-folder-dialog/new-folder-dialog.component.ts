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


import { Component, inject, Input, OnInit } from '@angular/core';
import { FileMetadata } from '../../model/metadata';
import { checkFolderExistsValidator, FileService } from '../../service/file.service';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { BehaviorSubject } from 'rxjs';
import { ToastService } from '../../../../toast/toast.service';

@Component({
    selector: 'cmdb-new-folder-dialog',
    templateUrl: './new-folder-dialog.component.html',
    styleUrls: ['./new-folder-dialog.component.scss'],
    standalone: false
})
export class NewFolderDialogComponent implements OnInit {

  private selectedFileElement: BehaviorSubject<any>;

  @Input()
  set selectedFileFolder( value: BehaviorSubject<any>) {
    this.selectedFileElement = value;
  }

  get selectedFileFolder(): BehaviorSubject<any> {
    return this.selectedFileElement;
  }

  public basicForm: UntypedFormGroup;

  static generateMetaData(parent: BehaviorSubject<any> ): FileMetadata {
    return new FileMetadata(
      {folder: true, ...{ parent: parent.getValue() == null ? null : parent.getValue().public_id }}
    );
  }

  private readonly fileService = inject(FileService);
  public readonly activeModal = inject(NgbActiveModal);
  private readonly toast = inject(ToastService);

  public ngOnInit(): void {
    this.basicForm = new UntypedFormGroup({
      name: new UntypedFormControl('', Validators.required)
    });
    this.basicForm.get('name').setAsyncValidators(checkFolderExistsValidator(this.fileService,
      NewFolderDialogComponent.generateMetaData(this.selectedFileFolder)));
  }

  public get name() {
    return this.basicForm.get('name');
  }

  public createFolder(): void {
    if(this.basicForm.invalid){
      this.toast.error('Please fill the required field')
      return;
    }
    const folder = new File(['folder'], this.name.value, {
      type: 'application/json',
    });
    this.fileService.postFile( folder, NewFolderDialogComponent.generateMetaData(this.selectedFileElement))
      .subscribe((resp: any) => {
        this.toast.info(`Folder was successfully created: ${this.name.value}`);
        this.activeModal.close({data: resp});
      });
  }
}
