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

import { OscalCatalog, OscalCatalogManifest } from '../models/oscal-catalog.model';
import { CatalogImportControl } from '../models/control-measure.model';

/** Location of the manifest inside the Angular bundle, relative to the base href. */
export const OSCAL_CATALOG_MANIFEST = 'assets/oscal/catalogs/manifest.json';

/**
 * Reads the OSCAL catalogs that ship with the frontend bundle (no backend involved)
 * and builds the URLs the bundled OSCAL viewer is opened with.
 */
@Injectable({ providedIn: 'root' })
export class OscalCatalogService {
    private readonly http = inject(HttpClient);

    private manifest$: Observable<OscalCatalogManifest> | null = null;

    /** Loads the manifest once and replays it to later subscribers. A failed load is retried on the next call. */
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

    /** Resolves a bundle-relative path against the document base href (works under a sub-path deployment). */
    public toAbsoluteUrl(path: string): string {
        return new URL(path, document.baseURI).toString();
    }

    /**
     * URL of the viewer page showing the given catalog. The viewer uses hash routing, so the
     * catalog location travels in the fragment and the static server only ever sees index.html.
     * `embedded` is set for the iframe on the catalog page: the viewer then hides its own header
     * so it blends into the DATAGERRY page; standalone (new tab) it shows a slim DATAGERRY header.
     */
    public getViewerUrl(manifest: OscalCatalogManifest, catalog: OscalCatalog, embedded = false): string {
        const catalogUrl = encodeURIComponent(this.toAbsoluteUrl(catalog.file));
        const embeddedParam = embedded ? '&embedded=1' : '';

        return `${this.toAbsoluteUrl(manifest.viewer.path)}#/catalog?url=${catalogUrl}${embeddedParam}`;
    }

    /**
     * Loads a bundled catalog and flattens its controls (nested groups and control enhancements)
     * into the payload of the control import. Withdrawn controls are left out.
     */
    public getImportControls(catalog: OscalCatalog): Observable<CatalogImportControl[]> {
        return this.http.get<any>(this.toAbsoluteUrl(catalog.file)).pipe(
            map(doc => flattenOscalCatalog(doc?.catalog ?? doc))
        );
    }
}

/* ------------------------------------------------- OSCAL FLATTENING ------------------------------------------------- */

/** Max. length of a title derived from the statement when the control has no own title. */
const DERIVED_TITLE_LENGTH = 120;

/** Flattens an OSCAL catalog into one import entry per (non-withdrawn) control. */
export function flattenOscalCatalog(catalog: any): CatalogImportControl[] {
    const result: CatalogImportControl[] = [];

    const walkControls = (controls: any[], chapter: string[]): void => {
        for (const control of controls ?? []) {
            if (!isWithdrawn(control)) {
                result.push(toImportControl(control, chapter));
            }
            walkControls(control.controls, [...chapter, controlIdentifier(control)]);
        }
    };

    const walkGroups = (groups: any[], chapter: string[]): void => {
        for (const group of groups ?? []) {
            const path = [...chapter, group.title ?? group.id].filter(Boolean);
            walkControls(group.controls, path);
            walkGroups(group.groups, path);
        }
    };

    walkControls(catalog?.controls, []);
    walkGroups(catalog?.groups, []);

    return result;
}

function isWithdrawn(control: any): boolean {
    return (control.props ?? []).some((prop: any) => prop.name === 'status' && prop.value === 'withdrawn');
}

/** The human-readable label (e.g. "AC-1", "WLAN.1.1") when it is a short code, otherwise the control id. */
function controlIdentifier(control: any): string {
    const label = (control.props ?? []).find((prop: any) => prop.name === 'label' && !prop.class)?.value;
    return label && !/\s/.test(label) ? label : control.id;
}

function toImportControl(control: any, chapter: string[]): CatalogImportControl {
    const identifier = controlIdentifier(control);
    const params = new Map<string, string>();
    (control.params ?? []).forEach((param: any) => {
        const choices = (param.select?.choice ?? []).join(' | ');
        const text = param.label || (param.values ?? []).join(', ') || (choices && `one of: ${choices}`) || param.id;
        params.set(param.id, text);
    });

    const statement = (control.parts ?? []).filter((part: any) => part.name === 'statement');
    const description = statement.map((part: any) => partText(part, params, 0)).join('\n').trim();

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

/** Prose of a part and its sub-parts, indented by depth, with "{{ insert: param, id }}" resolved. */
function partText(part: any, params: Map<string, string>, depth: number): string {
    const label = (part.props ?? []).find((prop: any) => prop.name === 'label')?.value;
    const prose = (part.prose ?? '').replace(
        /\{\{\s*insert:\s*param,\s*([^}\s]+)\s*\}\}/g,
        (_: string, id: string) => `[${params.get(id) ?? id}]`
    );
    const own = [label, prose].filter(Boolean).join(' ').trim();
    const lines = own ? ['  '.repeat(depth) + own] : [];

    (part.parts ?? []).forEach((child: any) => {
        const text = partText(child, params, own ? depth + 1 : depth);
        if (text) {
            lines.push(text);
        }
    });

    return lines.join('\n');
}
