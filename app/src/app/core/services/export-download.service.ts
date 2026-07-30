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
import { inject, Injectable, InjectionToken } from '@angular/core';
import { HttpResponse } from '@angular/common/http';

import { saveAs } from 'file-saver';

import { ExportFallbackName } from '../models/export-download.model';
import { buildFallbackExportFilename, readServerExportFilename } from '../utils/export-filename.util';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Injected so tests can observe the save. */
export const FILE_SAVER = new InjectionToken<(blob: Blob, filename: string) => void>('FILE_SAVER', {
    providedIn: 'root',
    factory: () => saveAs
});

/** Saves an export under the filename the backend sent. */
@Injectable({
    providedIn: 'root'
})
export class ExportDownloadService {

    private readonly saveFile = inject(FILE_SAVER);

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** @param fallback Used only when the server sent no filename. */
    public save(response: HttpResponse<Blob>, fallback: ExportFallbackName): void {
        if (!response?.body) {
            return;
        }

        this.saveFile(response.body, this.resolveFilename(response, fallback));
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private resolveFilename(response: HttpResponse<Blob>, fallback: ExportFallbackName): string {
        return readServerExportFilename(response) ?? buildFallbackExportFilename(fallback, new Date());
    }
}
