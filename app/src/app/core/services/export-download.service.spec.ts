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
import { TestBed } from '@angular/core/testing';
import { HttpHeaders, HttpResponse } from '@angular/common/http';

import { ExportDownloadService, FILE_SAVER } from './export-download.service';
import { ExportKind } from '../models/export-download.model';

/* ------------------------------------------------------------------------------------------------------------------ */

describe('ExportDownloadService', () => {
    let service: ExportDownloadService;
    let saveFile: jasmine.Spy<(blob: Blob, filename: string) => void>;

    /** Builds an export response, optionally carrying a server-issued filename. */
    function exportResponse(contentDisposition?: string, body: Blob | null = new Blob(['id,name'])): HttpResponse<Blob> {
        const headers = contentDisposition === undefined
            ? new HttpHeaders()
            : new HttpHeaders({ 'Content-Disposition': contentDisposition });

        return new HttpResponse<Blob>({ body, headers });
    }


    beforeEach(() => {
        saveFile = jasmine.createSpy('saveFile');

        TestBed.configureTestingModule({
            providers: [
                ExportDownloadService,
                { provide: FILE_SAVER, useValue: saveFile }
            ]
        });

        service = TestBed.inject(ExportDownloadService);
    });

    /* ---------------------------------------------- SERVER FILENAME ----------------------------------------------- */

    it('saves under the filename the server sent', () => {
        const response = exportResponse('attachment; filename="2026_07_21-13_05_00_objects_router.csv"');

        service.save(response, { kind: ExportKind.Objects, extension: 'csv' });

        expect(saveFile).toHaveBeenCalledOnceWith(response.body, '2026_07_21-13_05_00_objects_router.csv');
    });


    it('prefers the server filename over the fallback even when the extensions disagree', () => {
        const response = exportResponse('attachment; filename="2026_07_21-13_05_00_types_47.json"');

        service.save(response, { kind: ExportKind.Objects, extension: 'csv' });

        expect(saveFile.calls.mostRecent().args[1]).toBe('2026_07_21-13_05_00_types_47.json');
    });


    it('hands the response body through untouched', () => {
        const response = exportResponse('attachment; filename="export.json"');

        service.save(response, { kind: ExportKind.Types, extension: 'json' });

        expect(saveFile.calls.mostRecent().args[0]).toBe(response.body);
    });

    /* -------------------------------------------------- FALLBACK -------------------------------------------------- */

    it('falls back to a local name when the header is not readable', () => {
        service.save(exportResponse(), { kind: ExportKind.Objects, extension: 'csv' });

        expect(saveFile).toHaveBeenCalledTimes(1);
        expect(saveFile.calls.mostRecent().args[1]).toMatch(/^\d{4}_\d{2}_\d{2}-\d{2}_\d{2}_\d{2}_objects\.csv$/);
    });


    it('marks a fallback type export as such', () => {
        service.save(exportResponse(), { kind: ExportKind.Types, extension: 'json' });

        expect(saveFile.calls.mostRecent().args[1]).toMatch(/_types\.json$/);
    });

    /* ------------------------------------------------- EMPTY BODY ------------------------------------------------- */

    it('saves nothing when the response carries no file', () => {
        service.save(exportResponse('attachment; filename="export.csv"', null), {
            kind: ExportKind.Objects,
            extension: 'csv'
        });

        expect(saveFile).not.toHaveBeenCalled();
    });


    it('saves nothing when there is no response at all', () => {
        service.save(undefined as unknown as HttpResponse<Blob>, { kind: ExportKind.Objects, extension: 'csv' });

        expect(saveFile).not.toHaveBeenCalled();
    });
});
