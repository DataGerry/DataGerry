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
*/
import { PortNamePreview, PortPreviewFace } from '../models/port-bulk.types';
import { PortSide } from '../models/ports-overview.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** How many generated names are listed before the rest is summed up. */
export const PREVIEW_NAME_LIMIT = 12;

const FACE_TITLES: Record<PortSide, string> = {
    [PortSide.SINGLE]: 'Ports',
    [PortSide.FRONT]: 'Front ports',
    [PortSide.REAR]: 'Rear ports'
};

/** One face of the preview, prepared for the summary the user approves. */
export interface PreviewFaceView {
    title: string;
    count: number;
    range: string;
    names: string[];
    hiddenNames: number;
    duplicates: string[];
    existing: string[];
}


/** Everything the last step shows about a preview, so the wizard holds one value instead of four. */
export interface PortPreviewSummary {
    faces: PreviewFaceView[];
    totalPorts: number;
    internalConnections: number;
    hasCollisions: boolean;
}


/** What the last step shows before a preview has been fetched, and after a change invalidates it. */
export const EMPTY_PREVIEW_SUMMARY: PortPreviewSummary = {
    faces: [],
    totalPorts: 0,
    internalConnections: 0,
    hasCollisions: false
};


export function toPreviewSummary(preview: PortNamePreview | null): PortPreviewSummary {
    if (!preview) {
        return EMPTY_PREVIEW_SUMMARY;
    }

    return {
        faces: toPreviewFaceViews(preview),
        totalPorts: preview.total ?? 0,
        internalConnections: preview.pairs?.length ?? 0,
        hasCollisions: hasNameCollisions(preview)
    };
}


export function toPreviewFaceViews(preview: PortNamePreview | null): PreviewFaceView[] {
    return (preview?.faces ?? []).map((face) => toFaceView(face));
}


/** True while any face carries a collision - the backend refuses the whole batch in that case. */
export function hasNameCollisions(preview: PortNamePreview | null): boolean {
    return (preview?.faces ?? []).some(
        (face) => (face.collisions?.duplicates?.length ?? 0) > 0 || (face.collisions?.existing?.length ?? 0) > 0
    );
}


/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

function toFaceView(face: PortPreviewFace): PreviewFaceView {
    const names = face.names ?? [];

    return {
        title: FACE_TITLES[face.side] ?? 'Ports',
        count: names.length,
        range: nameRange(names),
        names: names.slice(0, PREVIEW_NAME_LIMIT),
        hiddenNames: Math.max(names.length - PREVIEW_NAME_LIMIT, 0),
        duplicates: face.collisions?.duplicates ?? [],
        existing: face.collisions?.existing ?? []
    };
}


function nameRange(names: string[]): string {
    if (names.length === 0) {
        return '';
    }

    const first = names[0];
    const last = names[names.length - 1];

    return first === last ? first : `${ first } – ${ last }`;
}
