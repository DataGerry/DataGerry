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
import { Component, OnDestroy, inject } from '@angular/core';

import { MovingDirection } from '@rg-software/angular-archwizard';
import { Subscription, finalize } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { ImportService } from 'src/app/modules/import/services/import.service';

import { ImportTypeAction, ImportTypeEntry, ImportTypeResponse } from '../../../models/import-type.models';
import { ParsedTypeFile } from '../select-file-drag-drop/select-file-drag-drop.component';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-import-types',
    templateUrl: './import-types.component.html',
    styleUrls: ['./import-types.component.scss'],
    standalone: false
})
export class ImportTypesComponent implements OnDestroy {
    private readonly importService = inject(ImportService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);

    public fileName = '';
    public fileSize: number = undefined;
    public parsedTypes: ImportTypeEntry[] = [];
    public action: ImportTypeAction = 'create';

    public importResponse: ImportTypeResponse = undefined;
    public isImporting = false;
    public isLoading$ = this.loaderService.isLoading$;

    /**
     * Guards every forward navigation of the file and preview steps: an upload without a single type
     * has nothing to import. Bound to the steps' `canExit`, so the wizard blocks the navigation bar
     * and any programmatic jump too, not just the disabled buttons.
     */
    public readonly canLeaveWithTypes = (direction: MovingDirection): boolean => {
        return direction !== MovingDirection.Forwards || this.parsedTypes.length > 0;
    };

    private importSubscription = new Subscription();

    /** The upload as it was read from the file — `parsedTypes` is the prunable working copy of it. */
    private uploadedTypes: ImportTypeEntry[] = [];

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    public ngOnDestroy(): void {
        this.importSubscription?.unsubscribe();
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onFileParsed(parsed: ParsedTypeFile): void {
        this.fileName = parsed.file?.name ?? '';
        this.fileSize = parsed.file?.size;
        this.uploadedTypes = parsed.types;
        this.parsedTypes = [...parsed.types];
        this.importResponse = undefined;
    }


    public onFileCleared(): void {
        this.fileName = '';
        this.fileSize = undefined;
        this.uploadedTypes = [];
        this.parsedTypes = [];
        this.importResponse = undefined;
    }


    /**
     * Returning to the file step re-establishes the types the file carries. The step still shows the
     * picked file, so a review that was pruned down to nothing must not leave it unable to continue.
     */
    public onFileStepEnter(): void {
        if (this.uploadedTypes.length === 0 || this.parsedTypes.length === this.uploadedTypes.length) {
            return;
        }

        this.parsedTypes = [...this.uploadedTypes];
        this.importResponse = undefined;
    }


    public onActionChange(action: ImportTypeAction): void {
        this.action = action;
    }


    /** Removing an entry has to hand a new array down, so the preview list picks the change up. */
    public onTypeRemoved(index: number): void {
        this.parsedTypes = this.parsedTypes.filter((_, position) => position !== index);
        // A changed upload invalidates a report the user may already have seen.
        this.importResponse = undefined;
    }


    public startImport(): void {
        if (this.isImporting || this.parsedTypes.length === 0) {
            return;
        }

        const formData = new FormData();
        formData.append('uploadFile', JSON.stringify(this.parsedTypes));

        const request = this.action === 'update'
            ? this.importService.postUpdateTypeParser(formData)
            : this.importService.postCreateTypeParser(formData);

        this.isImporting = true;
        this.loaderService.show();

        this.importSubscription = request
            .pipe(finalize(() => {
                this.isImporting = false;
                this.loaderService.hide();
            }))
            .subscribe({
                next: (response: ImportTypeResponse) => {
                    this.importResponse = {
                        message: response?.message,
                        success_imports: response?.success_imports ?? 0,
                        failed_imports: response?.failed_imports ?? []
                    };
                },
                error: (error) => {
                    this.toastService.error(error?.error?.message ?? 'The types could not be imported.');
                }
            });
    }
}
