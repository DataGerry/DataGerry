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

/** One bundled OSCAL catalog, as listed in `assets/oscal/catalogs/manifest.json`. */
export interface OscalCatalog {
    id: string;
    title: string;
    publisher: string;
    version: string;
    lastModified: string;
    language: string;
    groups: number;
    controls: number;
    /** Path of the catalog JSON, relative to the app base href. */
    file: string;
    /** Size of the catalog JSON in bytes. */
    size: number;
    license: string;
    /** Path of the license text, relative to the app base href. */
    licenseFile: string;
    /** Upstream location the catalog was taken from. */
    source: string;
}

/** The bundled OSCAL viewer that renders the catalogs. */
export interface OscalViewerInfo {
    /** Path of the viewer entry page, relative to the app base href. */
    path: string;
    name: string;
    license: string;
    licenseFile: string;
    source: string;
    notes?: string;
}

export interface OscalCatalogManifest {
    schemaVersion: number;
    viewer: OscalViewerInfo;
    catalogs: OscalCatalog[];
}
