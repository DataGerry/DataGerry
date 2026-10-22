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
import { ChangeDetectionStrategy, Component, DestroyRef, inject } from '@angular/core';
import { AsyncPipe } from '@angular/common';
import { HttpResponse } from '@angular/common/http';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { finalize } from 'rxjs';

import { CoreModule } from '../../core/core.module';
import { LayoutModule } from '../../layout/layout.module';

import { FileService } from '../export.service';
import { LoaderService } from '../../core/services/loader.service';
import { ExportDownloadService } from '../../core/services/export-download.service';
import { ToastService } from '../../layout/toast/toast.service';

import { ExportKind } from '../../core/models/export-download.model';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-export-data-model',
    templateUrl: './export-data-model.component.html',
    styleUrls: ['./export-data-model.component.scss'],
    imports: [AsyncPipe, CoreModule, LayoutModule],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class ExportDataModelComponent {

    private readonly exportService = inject(FileService);
    private readonly exportDownloadService = inject(ExportDownloadService);
    private readonly toastService = inject(ToastService);
    private readonly loaderService = inject(LoaderService);
    private readonly destroyRef = inject(DestroyRef);

    public readonly isLoading$ = this.loaderService.isLoading$;

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public exportDataModel(): void {
        this.loaderService.show();

        this.exportService.callExportDataModelRoute()
            .pipe(
                finalize(() => this.loaderService.hide()),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (response: HttpResponse<Blob>) => this.downloadDataModel(response),
                error: () => this.toastService.error('The data model could not be exported.')
            });
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private downloadDataModel(response: HttpResponse<Blob>): void {
        this.exportDownloadService.save(response, { kind: ExportKind.Configuration, extension: 'json' });
    }
}
