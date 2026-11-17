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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

import { inject, Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, catchError, map, shareReplay, throwError } from 'rxjs';

import {
    OscalCatalog,
    OscalCatalogContent,
    OscalCatalogDocument,
    OscalCatalogManifest,
    OscalControl,
    OscalGroup,
    OscalPart
} from '../models/oscal-catalog.model';
import { CatalogImportControl } from '../models/control-measure.model';

/** Relative to the base href. */
export const OSCAL_CATALOG_MANIFEST = 'assets/oscal/catalogs/manifest.json';

/** Reads the OSCAL catalogs bundled with the frontend; no backend involved. */
@Injectable({ providedIn: 'root' })
export class OscalCatalogService {
    private readonly http = inject(HttpClient);

    private manifest$: Observable<OscalCatalogManifest> | null = null;

    /** Cached; a failed load is retried on the next call. */
    public getManifest(): Observable<OscalCatalogManifest> {
        if (!this.manifest$) {
            this.manifest$ = this.http.get<OscalCatalogManifest>(this.toAbsoluteUrl(OSCAL_CATALOG_MANIFEST)).pipe(
                catchError(err => {
                    this.manifest$ = null;
                    return throwError(() => err);
                }),
                shareReplay(1)
            );
        }

        return this.manifest$;
    }

    /** Resolves against the base href, so sub-path deployments work. */
    public toAbsoluteUrl(path: string): string {
        return new URL(path, document.baseURI).toString();
    }

    /** The viewer uses hash routing; `embedded` hides its header inside the iframe. */
    public getViewerUrl(manifest: OscalCatalogManifest, catalog: OscalCatalog, embedded = false): string {
        const catalogUrl = encodeURIComponent(this.toAbsoluteUrl(catalog.file));
        const embeddedParam = embedded ? '&embedded=1' : '';

        return `${this.toAbsoluteUrl(manifest.viewer.path)}#/catalog?url=${catalogUrl}${embeddedParam}`;
    }

    public downloadCatalog(catalog: OscalCatalog): Observable<Blob> {
        return this.http.get(this.toAbsoluteUrl(catalog.file), { responseType: 'blob' });
    }

    public getFileName(catalog: OscalCatalog): string {
        return catalog.file.split('/').pop() || `${catalog.id}.json`;
    }

    /** Withdrawn controls are left out. */
    public getImportControls(catalog: OscalCatalog): Observable<CatalogImportControl[]> {
        return this.http.get<OscalCatalogDocument>(this.toAbsoluteUrl(catalog.file)).pipe(
            map(doc => flattenOscalCatalog(doc?.catalog))
        );
    }
}

/* ------------------------------------------------- OSCAL FLATTENING ------------------------------------------------- */

const DERIVED_TITLE_LENGTH = 120;

/** One import entry per control, including nested groups and enhancements. */
export function flattenOscalCatalog(catalog: OscalCatalogContent | undefined): CatalogImportControl[] {
    const result: CatalogImportControl[] = [];

    const walkControls = (controls: OscalControl[] | undefined, chapter: string[]): void => {
        for (const control of controls ?? []) {
            if (!isWithdrawn(control)) {
                result.push(toImportControl(control, chapter));
            }
            walkControls(control.controls, [...chapter, controlIdentifier(control)]);
        }
    };

    const walkGroups = (groups: OscalGroup[] | undefined, chapter: string[]): void => {
        for (const group of groups ?? []) {
            const path = [...chapter, group.title ?? group.id ?? ''].filter(Boolean);
            walkControls(group.controls, path);
            walkGroups(group.groups, path);
        }
    };

    walkControls(catalog?.controls, []);
    walkGroups(catalog?.groups, []);

    return result;
}

function isWithdrawn(control: OscalControl): boolean {
    return (control.props ?? []).some(prop => prop.name === 'status' && prop.value === 'withdrawn');
}

/** The label (e.g. "AC-1") when it is a short code, otherwise the control id. */
function controlIdentifier(control: OscalControl): string {
    const label = (control.props ?? []).find(prop => prop.name === 'label' && !prop.class)?.value;
    return label && !/\s/.test(label) ? label : control.id;
}

function toImportControl(control: OscalControl, chapter: string[]): CatalogImportControl {
    const identifier = controlIdentifier(control);
    const params = new Map<string, string>();
    (control.params ?? []).forEach(param => {
        const choices = (param.select?.choice ?? []).join(' | ');
        const text = param.label || (param.values ?? []).join(', ') || (choices && `one of: ${choices}`) || param.id;
        params.set(param.id, text);
    });

    const statement = (control.parts ?? []).filter(part => part.name === 'statement');
    const description = statement.map(part => partText(part, params, 0)).join('\n').trim();

    let title = (control.title ?? '').trim();
    if (!title || title === identifier || title === control.id) {
        const firstLine = description.split('\n')[0] ?? '';
        title = firstLine.length > DERIVED_TITLE_LENGTH ? `${firstLine.slice(0, DERIVED_TITLE_LENGTH - 3)}...` : firstLine;
    }

    return {
        identifier,
        title: title || identifier,
        chapter: chapter.length ? chapter.join(' / ') : null,
        description: description || null
    };
}

/** Indented by depth, with "{{ insert: param, id }}" resolved. */
function partText(part: OscalPart, params: Map<string, string>, depth: number): string {
    const label = (part.props ?? []).find(prop => prop.name === 'label')?.value;
    const prose = (part.prose ?? '').replace(
        /\{\{\s*insert:\s*param,\s*([^}\s]+)\s*\}\}/g,
        (_: string, id: string) => `[${params.get(id) ?? id}]`
    );
    const own = [label, prose].filter(Boolean).join(' ').trim();
    const lines = own ? ['  '.repeat(depth) + own] : [];

    (part.parts ?? []).forEach(child => {
        const text = partText(child, params, own ? depth + 1 : depth);
        if (text) {
            lines.push(text);
        }
    });

    return lines.join('\n');
}
