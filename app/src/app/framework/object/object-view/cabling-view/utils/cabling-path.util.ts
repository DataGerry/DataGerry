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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { CablingPathSample } from '../models/cabling-tooltip.types';
import { CablingPoint } from '../models/cabling.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Canvas pixels between two samples; the nearest point is refined from there. */
const SAMPLE_STEP = 6;

/** Refining stops once the step is shorter than this. */
const PRECISION = 0.5;


/** Points along the path every few canvas pixels, both ends included. */
export function samplePath(path: SVGGeometryElement, step = SAMPLE_STEP): CablingPathSample[] {
    const total = path.getTotalLength();
    const count = Math.max(1, Math.ceil(total / step));

    return Array.from({ length: count + 1 }, (_, index) => {
        const length = (total * index) / count;
        const { x, y } = path.getPointAtLength(length);

        return { length, x, y };
    });
}


/** The point of the path closest to `target`: the nearest sample, refined by halving the step around it. */
export function nearestPointOnPath(
    path: SVGGeometryElement,
    samples: readonly CablingPathSample[],
    target: CablingPoint
): CablingPoint {
    let best = samples[0];
    let bestDistance = distance(best, target);

    for (const sample of samples) {
        const sampleDistance = distance(sample, target);

        if (sampleDistance < bestDistance) {
            best = sample;
            bestDistance = sampleDistance;
        }
    }

    const total = samples[samples.length - 1].length;
    let step = samples.length > 1 ? samples[1].length : 0;

    while (step > PRECISION) {
        step /= 2;

        for (const length of [best.length - step, best.length + step]) {
            if (length < 0 || length > total) {
                continue;
            }

            const { x, y } = path.getPointAtLength(length);
            const candidateDistance = distance({ x, y }, target);

            if (candidateDistance < bestDistance) {
                best = { length, x, y };
                bestDistance = candidateDistance;
            }
        }
    }

    return { x: best.x, y: best.y };
}

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

function distance(first: CablingPoint, second: CablingPoint): number {
    return Math.hypot(first.x - second.x, first.y - second.y);
}
