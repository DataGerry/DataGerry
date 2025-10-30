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

/** Promise-based image loader (use for both SVG and PNG data URLs). */
export function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('Image load failed'));
    img.src = url;
  });
}

/** Convert an SVG markup string into a PNG data URL at the given dimensions. */
export async function svgStringToPngDataUrl(
  svgString: string,
  width: number,
  height: number,
  pixelRatio: number,
  background: string
): Promise<string> {
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.floor(width * pixelRatio));
  canvas.height = Math.max(1, Math.floor(height * pixelRatio));
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('[CI Export] Canvas not supported');
  ctx.scale(pixelRatio, pixelRatio);
  ctx.fillStyle = background || '#ffffff';
  ctx.fillRect(0, 0, width, height);

  const blob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  try {
    const img = await loadImage(url);
    ctx.drawImage(img, 0, 0, width, height);
    return canvas.toDataURL('image/png');
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Build a CLEAN SVG from the live .connections-svg and shift its content so nothing gets clipped. */
export function buildShiftedConnectionsSvg(
  svgEl: SVGSVGElement,
  width: number,
  height: number,
  translateX: number,
  translateY: number,
  flattenGradientStrokes: boolean = true
): string {
  const NS = 'http://www.w3.org/2000/svg';
  const XLINK = 'http://www.w3.org/1999/xlink';

  // Deep clone the actual SVG (keeps <defs>, gradients, markers intact)
  const clone = svgEl.cloneNode(true) as SVGSVGElement;

  // Ensure proper namespaces & geometry on root
  clone.setAttribute('xmlns', NS);
  clone.setAttribute('xmlns:xlink', XLINK);
  clone.setAttribute('width', String(width));
  clone.setAttribute('height', String(height));
  clone.setAttribute('viewBox', `0 0 ${width} ${height}`);
  clone.setAttribute('overflow', 'visible');

  // Wrap all non-defs children into a shifted group
  const doc = document.implementation.createDocument(NS, 'svg', null);
  const root = doc.importNode(clone, true) as SVGSVGElement;

  const defs = root.querySelector('defs');
  const wrap = doc.createElementNS(NS, 'g');
  wrap.setAttribute('transform', `translate(${translateX},${translateY})`);

  const toMove: ChildNode[] = [];
  Array.from(root.childNodes).forEach((n) => {
    if (!(n.nodeType === 1 && (n as Element).tagName.toLowerCase() === 'defs')) {
      toMove.push(n);
    }
  });
  toMove.forEach(n => wrap.appendChild(n));
  if (defs && defs.parentNode === root) {
    root.insertBefore(wrap, defs.nextSibling);
  } else {
    root.insertBefore(wrap, root.firstChild);
  }

  // Normalize strokes and optionally flatten gradients to a solid color
  const fallbackStroke = '#2cb5b5'; // teal-like color between green and blue
  root.querySelectorAll<SVGPathElement>('path.connection-path').forEach(p => {
    p.setAttribute('fill', 'none');
    p.setAttribute('stroke-linecap', 'round');
    p.setAttribute('stroke-linejoin', 'round');
    if (flattenGradientStrokes) {
      const stroke = p.getAttribute('stroke') || '';
      if (stroke.includes('url(')) {
        p.setAttribute('stroke', fallbackStroke);
      }
    }
  });

  const xml = new XMLSerializer().serializeToString(root);
  return `<?xml version="1.0" encoding="UTF-8"?>\n${xml}`;
}