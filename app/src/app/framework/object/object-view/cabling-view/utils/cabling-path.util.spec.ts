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
import { nearestPointOnPath, samplePath } from './cabling-path.util';

describe('cabling-path.util', () => {
    let svg: SVGSVGElement;

    const path = (d: string): SVGPathElement => {
        const element = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        element.setAttribute('d', d);
        svg.appendChild(element);

        return element;
    };

    beforeEach(() => {
        svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        document.body.appendChild(svg);
    });

    afterEach(() => svg.remove());

    it('samples both ends and evenly between them', () => {
        const samples = samplePath(path('M0 0 L100 0'), 10);

        expect(samples.length).toBe(11);
        expect(samples[0]).toEqual({ length: 0, x: 0, y: 0 });
        expect(samples[10].x).toBeCloseTo(100, 3);
        expect(samples[5].length).toBeCloseTo(50, 3);
    });

    it('keeps one sample at each end of an empty path', () => {
        expect(samplePath(path('M5 5'))).toEqual([{ length: 0, x: 5, y: 5 }, { length: 0, x: 5, y: 5 }]);
    });

    it('finds the point under a pointer beside a straight cable', () => {
        const line = path('M0 0 L100 0');
        const nearest = nearestPointOnPath(line, samplePath(line), { x: 43.2, y: 7 });

        expect(nearest.x).toBeCloseTo(43.2, 0);
        expect(nearest.y).toBeCloseTo(0, 3);
    });

    it('finds the point on a curve to within half a pixel', () => {
        const curve = path('M0 0 C100 0 100 100 200 100');
        const onCurve = curve.getPointAtLength(137);
        const nearest = nearestPointOnPath(curve, samplePath(curve), { x: onCurve.x, y: onCurve.y });

        expect(Math.hypot(nearest.x - onCurve.x, nearest.y - onCurve.y)).toBeLessThan(0.5);
    });

    it('stops at the end of the path past its last point', () => {
        const line = path('M0 0 L100 0');

        expect(nearestPointOnPath(line, samplePath(line), { x: 180, y: 20 }).x).toBeCloseTo(100, 3);
    });
});
