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
    styleUrls: ['./select-file.component.scss'],
    standalone: false
})
export class SelectFileComponent implements OnInit, OnDestroy {

    private defaultFileFormat: string = '';
    public fileForm: UntypedFormGroup;
    public selectedFileFormat: string = '';
    public formatOptions: { label: string; value: string }[] = [];

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


    public get isJsonFormat(): boolean {
        return (this.fileFormat.value ?? '').toLowerCase() === 'json';
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
            this.formatOptions = ((importers ?? []) as any[]).map((importer) => ({
                label: (importer?.name ?? '').toUpperCase(),
                value: importer?.name
            }));
        });

        this.syncFileControlState(this.fileFormat.value);

        this.fileFormatChangeSubscription = this.fileFormat.valueChanges.subscribe((format: string) => {
            this.formatChange.emit(format);
            this.selectedFileFormat = format ? `.${ format }` : '';
            // A file picked for one format must not carry over to another.
            this.file.reset(null, { emitEvent: false });
            this.syncFileControlState(format);
        });

        this.fileChangeSubscription = this.file.valueChanges.subscribe((file: File | null) => {
            if (file) {
                this.fileChange.emit(file);
            }
        });
    }


    public ngOnDestroy(): void {
        this.importerDefinitionSubscription?.unsubscribe();
        this.fileFormatChangeSubscription?.unsubscribe();
        this.fileChangeSubscription?.unsubscribe();
    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    /** File selection stays disabled until a format is chosen; the dropzone reflects this via the form. */
    private syncFileControlState(format: string): void {
        if (format) {
            this.file.enable({ emitEvent: false });
        } else {
            this.file.disable({ emitEvent: false });
        }
    }
}
