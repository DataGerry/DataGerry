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
import { Observable, catchError, shareReplay, throwError } from 'rxjs';

import { OscalCatalog, OscalCatalogManifest } from '../models/oscal-catalog.model';

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
}
