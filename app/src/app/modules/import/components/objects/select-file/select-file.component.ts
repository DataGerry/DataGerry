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
import { Component, EventEmitter, OnDestroy, OnInit, Output } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';

import { finalize, Subscription } from 'rxjs';

import { ImportService } from '../../../services/import.service';
import { LoaderService } from 'src/app/core/services/loader.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-select-file',
    templateUrl: './select-file.component.html',
    styleUrls: ['./select-file.component.scss']
})
export class SelectFileComponent implements OnInit, OnDestroy {

    private defaultFileFormat: string = '';
    public fileForm: UntypedFormGroup;
    public fileName: string = 'Choose file';
    public selectedFileFormat: string = `.${ this.defaultFileFormat }`;
    public importerTypes: any[] = [];

    // Loading subscription
    private importerDefinitionSubscription: Subscription;
    private fileFormatChangeSubscription: Subscription;
    private fileChangeSubscription: Subscription;

    // Event outputs
    @Output() public formatChange: EventEmitter<string>;
    @Output() public fileChange: EventEmitter<File>;

    public isLoading$ = this.loaderService.isLoading$;

/* ------------------------------------------------- GETTER / SETTER ------------------------------------------------ */

    public get fileFormat() {
        return this.fileForm.get('fileFormat');
    }


    public get file() {
        return this.fileForm.get('file');
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    public constructor(private importService: ImportService, private loaderService: LoaderService) {
        this.formatChange = new EventEmitter<string>();
        this.fileChange = new EventEmitter<File>();

        this.importerDefinitionSubscription = new Subscription();
        this.fileFormatChangeSubscription = new Subscription();
        this.fileChangeSubscription = new Subscription();

        this.fileForm = new UntypedFormGroup({
            fileFormat: new UntypedFormControl(this.defaultFileFormat, Validators.required),
            file: new UntypedFormControl(null, Validators.required)
        });
    }


    public ngOnInit(): void {
        this.loaderService.show();
        this.importerDefinitionSubscription = this.importService.getObjectImporters()
        .pipe(finalize(() => this.loaderService.hide())).subscribe(importers => {
            this.importerTypes = importers;
        });

        this.fileFormatChangeSubscription = this.fileFormat.valueChanges.subscribe((format: string) => {
            this.formatChange.emit(format);
            this.selectedFileFormat = `.${ format }`;
        });

        this.fileChangeSubscription = this.file.valueChanges.subscribe((file) => {
            this.fileChange.emit(file);
        });
    }


    public ngOnDestroy(): void {
        this.importerDefinitionSubscription?.unsubscribe();
        this.fileFormatChangeSubscription?.unsubscribe();
        this.fileChangeSubscription?.unsubscribe();
    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    public selectFile(files) {
        if (files.length > 0) {
            const file = files[0];
            this.fileForm.get('file').setValue(file);
            this.fileName = file.name;
        }
    }
}
