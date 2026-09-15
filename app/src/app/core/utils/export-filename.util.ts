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
import { HttpResponse } from '@angular/common/http';

import { ExportFallbackName } from '../models/export-download.model';
/* ------------------------------------------------------------------------------------------------------------------ */

const CONTENT_DISPOSITION_HEADER = 'Content-Disposition';
const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f]/g;

/** Reads the filename from `Content-Disposition`. Undefined when the header is not readable. */
export function readServerExportFilename(response: HttpResponse<unknown>): string | undefined {
    const header = response?.headers?.get(CONTENT_DISPOSITION_HEADER);

    return header ? toSafeFilename(parseContentDispositionFilename(header)) : undefined;
}


/** Client-side name, used only when the server sent none. e.g. `2026_07_30-14_05_00_objects.csv` */
export function buildFallbackExportFilename(fallback: ExportFallbackName, exportedAt: Date): string {
    const stamp = [
        exportedAt.getFullYear(),
        pad(exportedAt.getMonth() + 1),
        pad(exportedAt.getDate())
    ].join('_');

    const time = [
        pad(exportedAt.getHours()),
        pad(exportedAt.getMinutes()),
        pad(exportedAt.getSeconds())
    ].join('_');

    const stem = `${stamp}-${time}_${fallback.kind}`;

    return fallback.extension ? `${stem}.${fallback.extension}` : stem;
}

/* ------------------------------------------------------------------------------------------------------------------ */

/** Prefers the RFC 5987 `filename*` form; its `charset'lang'` prefix is dropped. */
function parseContentDispositionFilename(header: string): string | undefined {
    const encodedMatch = /filename\*=(?:[\w-]+'[\w-]*')?([^;]+)/i.exec(header);

    if (encodedMatch?.[1]) {
        return decodeFilename(encodedMatch[1].replace(/"/g, '').trim());
    }

    return /filename="?([^";]+)"?/i.exec(header)?.[1]?.trim();
}


/** A stray `%` would make decodeURIComponent throw and fail the download. */
function decodeFilename(value: string): string {
    try {
        return decodeURIComponent(value);
    } catch {
        return value;
    }
}


/** Keeps only the basename, so a `../` value cannot escape the download directory. */
function toSafeFilename(filename: string | undefined): string | undefined {
    if (!filename) {
        return undefined;
    }

    const basename = filename.split(/[\\/]/).pop() ?? '';
    const cleaned = basename.replace(CONTROL_CHARACTERS, '').replace(/^\.+/, '').trim();

    return cleaned || undefined;
}


function pad(value: number): string {
    return `${value}`.padStart(2, '0');
}
