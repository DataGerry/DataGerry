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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, OnInit } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { finalize } from 'rxjs';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { ImportService } from 'src/app/modules/import/services/import.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-import-types',
    templateUrl: './import-types.component.html',
    styleUrls: ['./import-types.component.scss'],
    standalone: false
})
export class ImportTypesComponent implements OnInit {
    public fileForm: UntypedFormGroup;
    public preview: any;
    public done: boolean = false;
    public errorHandling = [];
    public isLoading$ = this.loaderService.isLoading$;

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    public constructor(
        private importService: ImportService, 
        private loaderService: LoaderService,
        private toastService: ToastService 

    ) {

    }


    ngOnInit() {
        this.fileForm = new UntypedFormGroup({
        format: new UntypedFormControl('json', Validators.required),
        name: new UntypedFormControl('', Validators.required),
        size: new UntypedFormControl('', Validators.required),
        file: new UntypedFormControl(null, Validators.required),
        action: new UntypedFormControl('create', Validators.required),
        });

        this.fileForm.valueChanges.subscribe(newValue => {
        this.fileForm.get('file').patchValue(newValue.file, { onlySelf: true });
        });
    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    public importTypeFile() {

        if (this.fileForm.invalid) {
            this.toastService.error("Please complete all required fields.");
            return;
        }

        this.loaderService.show();
        const action = this.fileForm.get('action').value;
        const theJSON = JSON.stringify(this.fileForm.get('file').value);
        const formData = new FormData();
        formData.append('uploadFile', theJSON);

        if (action === 'update') {
            this.importService.postUpdateTypeParser(formData).pipe(finalize(() => this.loaderService.hide())).subscribe(res => {
                if (Object.keys(res).length > 0) {
                    this.errorHandling.push(res);
                }

                this.done = true;
            });
        } else {
            this.importService.postCreateTypeParser(formData).pipe(finalize(() => this.loaderService.hide())).subscribe(res => {
                if (Object.keys(res).length > 0) {
                    this.errorHandling.push(res);
                }

                this.done = true;
            });
        }
    }
}
