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
import { HttpHeaders, HttpResponse } from '@angular/common/http';

import { ExportKind } from '../models/export-download.model';
import { buildFallbackExportFilename, readServerExportFilename } from './export-filename.util';

/* ------------------------------------------------------------------------------------------------------------------ */

/** Builds an export response carrying the given `Content-Disposition`, or none at all. */
function responseWith(contentDisposition?: string): HttpResponse<Blob> {
    const headers = contentDisposition === undefined
        ? new HttpHeaders()
        : new HttpHeaders({ 'Content-Disposition': contentDisposition });

    return new HttpResponse<Blob>({ body: new Blob(['x']), headers });
}

/* ------------------------------------------------------------------------------------------------------------------ */

describe('readServerExportFilename', () => {

    /* ------------------------------------------------ SERVER NAMES ------------------------------------------------ */

    describe('names issued by the backend', () => {
        it('reads a quoted object export name', () => {
            const response = responseWith('attachment; filename="2026_07_21-13_05_00_objects_router.csv"');

            expect(readServerExportFilename(response)).toBe('2026_07_21-13_05_00_objects_router.csv');
        });


        it('reads a human-readable object export name', () => {
            const response = responseWith('attachment; filename="2026_07_21-13_05_00_objects_router_readable.csv"');

            expect(readServerExportFilename(response)).toBe('2026_07_21-13_05_00_objects_router_readable.csv');
        });


        it('reads a type export name', () => {
            const response = responseWith('attachment; filename="2026_07_21-13_05_00_types_47.json"');

            expect(readServerExportFilename(response)).toBe('2026_07_21-13_05_00_types_47.json');
        });


        it('reads an unquoted filename', () => {
            expect(readServerExportFilename(responseWith('attachment; filename=export.json'))).toBe('export.json');
        });


        it('trims surrounding whitespace', () => {
            expect(readServerExportFilename(responseWith('attachment; filename=  export.json  '))).toBe('export.json');
        });
    });

    /* --------------------------------------------- RFC 5987 ENCODING ---------------------------------------------- */

    describe('RFC 5987 encoding', () => {
        it('prefers filename* over the plain ASCII filename', () => {
            const response = responseWith(`attachment; filename="fallback.csv"; filename*=UTF-8''r%C3%B6uter.csv`);

            expect(readServerExportFilename(response)).toBe('röuter.csv');
        });


        it('drops a non-UTF-8 charset prefix instead of letting it leak into the name', () => {
            const response = responseWith(`attachment; filename*=ISO-8859-1'en'report.csv`);

            expect(readServerExportFilename(response)).toBe('report.csv');
        });


        it('keeps the raw value when the encoding is malformed', () => {
            // A stray % would make decodeURIComponent throw; a cosmetic header flaw must not fail the download
            const response = responseWith(`attachment; filename*=UTF-8''100%_done.csv`);

            expect(readServerExportFilename(response)).toBe('100%_done.csv');
        });
    });

    /* ------------------------------------------------- NO NAME ---------------------------------------------------- */

    describe('when no usable name is present', () => {
        it('returns undefined when the header is absent, as on a cross-origin API', () => {
            expect(readServerExportFilename(responseWith())).toBeUndefined();
        });


        it('returns undefined for an empty header', () => {
            expect(readServerExportFilename(responseWith(''))).toBeUndefined();
        });


        it('returns undefined when the header carries no filename parameter', () => {
            expect(readServerExportFilename(responseWith('attachment'))).toBeUndefined();
        });


        it('returns undefined when the name is nothing but dots', () => {
            expect(readServerExportFilename(responseWith('attachment; filename="..."'))).toBeUndefined();
        });


        it('tolerates a response without headers', () => {
            expect(readServerExportFilename(undefined as unknown as HttpResponse<Blob>)).toBeUndefined();
        });
    });

    /* ------------------------------------------------ SANITISING -------------------------------------------------- */

    describe('sanitising a server-supplied name', () => {
        it('strips a POSIX path so the download cannot escape the download directory', () => {
            const response = responseWith('attachment; filename="../../../etc/passwd"');

            expect(readServerExportFilename(response)).toBe('passwd');
        });


        it('strips a Windows path', () => {
            const response = responseWith('attachment; filename="C:\\Windows\\System32\\evil.csv"');

            expect(readServerExportFilename(response)).toBe('evil.csv');
        });


        it('drops leading dots so no hidden file is written', () => {
            expect(readServerExportFilename(responseWith('attachment; filename=".hidden.csv"'))).toBe('hidden.csv');
        });
    });
});

/* ------------------------------------------------------------------------------------------------------------------ */

describe('buildFallbackExportFilename', () => {

    it('names an object export by kind, moment and extension', () => {
        const filename = buildFallbackExportFilename(
            { kind: ExportKind.Objects, extension: 'csv' },
            new Date(2026, 6, 30, 14, 5, 0)
        );

        expect(filename).toBe('2026_07_30-14_05_00_objects.csv');
    });


    it('names a type export', () => {
        const filename = buildFallbackExportFilename(
            { kind: ExportKind.Types, extension: 'json' },
            new Date(2026, 0, 2, 3, 4, 5)
        );

        expect(filename).toBe('2026_01_02-03_04_05_types.json');
    });


    it('zero-pads every part so names sort chronologically', () => {
        const filename = buildFallbackExportFilename(
            { kind: ExportKind.Objects, extension: 'xml' },
            new Date(2026, 8, 9, 1, 2, 3)
        );

        expect(filename).toBe('2026_09_09-01_02_03_objects.xml');
    });


    it('uses a 24-hour clock so morning and afternoon exports never collide', () => {
        const morning = buildFallbackExportFilename(
            { kind: ExportKind.Objects, extension: 'csv' }, new Date(2026, 6, 30, 9, 0, 0)
        );
        const evening = buildFallbackExportFilename(
            { kind: ExportKind.Objects, extension: 'csv' }, new Date(2026, 6, 30, 21, 0, 0)
        );

        expect(morning).toBe('2026_07_30-09_00_00_objects.csv');
        expect(evening).toBe('2026_07_30-21_00_00_objects.csv');
    });


    it('omits the extension rather than ending the name in a dot', () => {
        const filename = buildFallbackExportFilename(
            { kind: ExportKind.Objects },
            new Date(2026, 6, 30, 14, 5, 0)
        );

        expect(filename).toBe('2026_07_30-14_05_00_objects');
    });
});
