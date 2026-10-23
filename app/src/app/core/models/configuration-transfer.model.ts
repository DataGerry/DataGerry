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
/* ------------------------------------------------------------------------------------------------------------------ */

/* -------------------------------------------------- CONSTANTS ------------------------------------------------- */

/** Limits the export route enforces on its body. */
export const CONFIGURATION_EXPORT_NAME_MAX_LENGTH = 255;
export const CONFIGURATION_EXPORT_DESCRIPTION_MAX_LENGTH = 4000;
export const CONFIGURATION_EXPORT_FILENAME_MAX_LENGTH = 255;

/* ------------------------------------------------- INTERFACES ------------------------------------------------ */

/** Body of `POST /configuration_transfer/export`; a null `filename` lets the backend generate one. */
export interface ConfigurationExportRequest {
    name: string;
    description: string;
    filename: string | null;
}

export interface ConfigurationTransferCounts {
    section_templates: number;
    types: number;
    categories: number;
    relations: number;
}

/** The `information` section of a transfer file. */
export interface ConfigurationTransferInformation {
    name: string;
    description: string;
    version: string;
    counts: ConfigurationTransferCounts;
}

/** Answer of `POST /configuration_transfer/import/preview`; `information` is null when that section is invalid. */
export interface ConfigurationImportPreview {
    information: ConfigurationTransferInformation | null;
    reset_blockers: string[];
    problems: string[];
    importable: boolean;
}
