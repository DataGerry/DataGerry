/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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

/** Measure min/max extents from positioned nodes and SVG connection group. */
export function computeContentBounds(canvasEl: HTMLElement): {
    minX: number; minY: number; maxX: number; maxY: number; width: number; height: number;
} {
    let minX = Number.POSITIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;

    // Nodes (absolutely positioned inside .nodes-container)
    const nodeEls = Array.from(canvasEl.querySelectorAll<HTMLElement>('.nodes-container .ci-node'));
    for (const el of nodeEls) {
        const left = readPx(el.style.left, el.offsetLeft);
        const top = readPx(el.style.top, el.offsetTop);
        const w = el.offsetWidth || el.clientWidth || 0;
        const h = el.offsetHeight || el.clientHeight || 0;
        minX = Math.min(minX, left);
        minY = Math.min(minY, top);
        maxX = Math.max(maxX, left + w);
        maxY = Math.max(maxY, top + h);
    }

    // SVG paths (use <g class="connections-group"> bbox if available)
    const group = canvasEl.querySelector<SVGGElement>('svg.connections-svg g.connections-group');
    if (group && typeof (group as any).getBBox === 'function') {
        try {
            const bbox = (group as any as SVGGraphicsElement).getBBox();
            minX = Math.min(minX, bbox.x);
            minY = Math.min(minY, bbox.y);
            maxX = Math.max(maxX, bbox.x + bbox.width);
            maxY = Math.max(maxY, bbox.y + bbox.height);
        } catch {
            // ignore getBBox errors (e.g., if element is display:none)
        }
    }

    // Fallback if no content
    if (!isFinite(minX) || !isFinite(minY) || !isFinite(maxX) || !isFinite(maxY)) {
        minX = 0; minY = 0; maxX = canvasEl.clientWidth; maxY = canvasEl.clientHeight;
    }

    return { minX, minY, maxX, maxY, width: maxX - minX, height: maxY - minY };
}

export function readPx(styleValue: string, fallback: number): number {
    if (!styleValue) return fallback || 0;
    const n = parseFloat(styleValue);
    return isNaN(n) ? (fallback || 0) : n;
}