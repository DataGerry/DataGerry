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

import { inject, Injectable } from '@angular/core';
import { CiExportPngOptions } from '../interfaces/graph.interfaces';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { loadImage, svgStringToPngDataUrl, buildShiftedConnectionsSvg } from './export-utils/svg-export.utils';
import { computeContentBounds } from './export-utils/bounds-utils';
import { waitForFonts, getComputedBg, downloadDataUrl, toggleExportingClass } from './export-utils/dom-utils';
import { timestamp, clamp } from './export-utils/general-utils';

@Injectable({ providedIn: 'root' })
export class CiExplorerExportService {
  private toastService = inject(ToastService);
  private readonly DEFAULT_MAX_MEGAPIXELS = 20; // ~20MP safety cap

  /** Export only(viewport). */
  async exportViewportToPng(
    viewportEl: HTMLElement,
    opts: CiExportPngOptions = {}
  ): Promise<string> {
    if (!viewportEl) throw new Error('[CI Export] viewport element is missing.');

    const {
      fileNamePrefix = 'ci-explorer',
      currentZoom = 1,
      backgroundColor,
      pixelRatioMax = 3
    } = opts;

    await waitForFonts();
    toggleExportingClass(viewportEl, true);

    const baseDpr = Math.max(1, window.devicePixelRatio || 1);
    const suggested = baseDpr / (currentZoom || 1);
    const pixelRatio = clamp(suggested, 1, pixelRatioMax);

    const fileName = `${fileNamePrefix}-${timestamp()}.png`;

    try {
      const { toSvg } = await import('html-to-image');
      // Render to SVG first to preserve SVG paths/markers reliably
      const svgString = await toSvg(viewportEl, {
        cacheBust: true,
        pixelRatio,
        backgroundColor: backgroundColor ?? getComputedBg(viewportEl),
      });

      const dataUrl = await svgStringToPngDataUrl(
        svgString,
        viewportEl.clientWidth,
        viewportEl.clientHeight,
        pixelRatio,
        backgroundColor ?? getComputedBg(viewportEl)
      );

      downloadDataUrl(dataUrl, fileName);
      return fileName;
    } catch (err) {
      this.toastService.error('Export failed. Try reducing graph size/zoom and retry.');
    } finally {
      toggleExportingClass(viewportEl, false);
    }
  }

  /**
   * Export the **entire** graph canvas as PNG:
   * - Computes bounds from nodes and SVG connections
   * - Neutralizes pan/zoom transform on the cloned element
   * - Captures everything inside `.graph-canvas`
   */
  async exportFullCanvasToPng(
    canvasEl: HTMLElement,            // <div class="graph-canvas" #graphCanvas>
    opts: CiExportPngOptions = {}
  ): Promise<string> {
    if (!canvasEl) return;
    const {
      fileNamePrefix = 'ci-explorer',
      backgroundColor,
      pixelRatioMax = 3,
      padding = 50
    } = opts;

    await waitForFonts();
    toggleExportingClass(canvasEl, true);

    // 1) Measure content bounds and add small safety pad to prevent arrow clipping
    const BBOX_PAD = 16;
    const b = computeContentBounds(canvasEl);
    const minX = Math.floor(b.minX) - BBOX_PAD;
    const minY = Math.floor(b.minY) - BBOX_PAD;
    const exportWidth  = Math.ceil(b.width  + padding * 2) + BBOX_PAD * 2;
    const exportHeight = Math.ceil(b.height + padding * 2) + BBOX_PAD * 2;

    // 2) Compute safe pixel ratio within megapixel cap
    const baseDpr = Math.max(1, window.devicePixelRatio || 1);
    let pixelRatio = clamp(baseDpr, 1, pixelRatioMax);
    const maxPx = this.DEFAULT_MAX_MEGAPIXELS * 1_000_000;
    const curPx = exportWidth * exportHeight * pixelRatio * pixelRatio;
    if (curPx > maxPx) {
      pixelRatio = Math.sqrt(maxPx / (exportWidth * exportHeight));
      pixelRatio = Math.max(1, Math.min(pixelRatio, pixelRatioMax));
    }

    // 3) Shared translation to rebase graph top-left to (padding, padding)
    const translateX = -minX + padding;
    const translateY = -minY + padding;

    try {
      // Prefer robust composite: SVG connections + HTML nodes
      const svgEl = canvasEl.querySelector('svg.connections-svg') as SVGSVGElement | null;
      const nodesEl = canvasEl.querySelector('.nodes-container') as HTMLElement | null;
      if (!svgEl || !nodesEl) throw new Error('layers-missing');

      // Prepare canvas
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.floor(exportWidth * pixelRatio));
      canvas.height = Math.max(1, Math.floor(exportHeight * pixelRatio));
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('no-2d');
      ctx.scale(pixelRatio, pixelRatio);
      ctx.fillStyle = backgroundColor ?? getComputedBg(canvasEl);
      ctx.fillRect(0, 0, exportWidth, exportHeight);

      // Draw connections as pure SVG image
      // IMPORTANT: for export reliability, flatten gradient strokes to a solid color
      const svgString = buildShiftedConnectionsSvg(svgEl, exportWidth, exportHeight, translateX, translateY, true);
      const svgUrl = URL.createObjectURL(new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' }));
      const svgImg = await loadImage(svgUrl);
      ctx.drawImage(svgImg, 0, 0, exportWidth, exportHeight);
      URL.revokeObjectURL(svgUrl);

      // Draw nodes via html-to-image PNG
      const { toPng } = await import('html-to-image');
      const nodesPngUrl = await toPng(nodesEl, {
        cacheBust: true,
        width: exportWidth,
        height: exportHeight,
        pixelRatio,
        backgroundColor: 'transparent',
        style: {
          transform: `translate(${translateX}px, ${translateY}px) scale(1)`,
          transformOrigin: 'top left',
        },
      });
      const nodesImg = await loadImage(nodesPngUrl);
      ctx.drawImage(nodesImg, 0, 0, exportWidth, exportHeight);

      const fileName = `${fileNamePrefix}-${timestamp()}.png`;
      downloadDataUrl(canvas.toDataURL('image/png'), fileName);
      return fileName;
    } catch (primaryErr) {
      try {
        const { toSvg } = await import('html-to-image');
        const svgString = await toSvg(canvasEl, {
          cacheBust: true,
          width: exportWidth,
          height: exportHeight,
          pixelRatio,
          backgroundColor: backgroundColor ?? getComputedBg(canvasEl),
          style: {
            transform: `translate(${translateX}px, ${translateY}px) scale(1)`,
            transformOrigin: 'top left',
          },
        });
        const dataUrl = await svgStringToPngDataUrl(
          svgString,
          exportWidth,
          exportHeight,
          pixelRatio,
          backgroundColor ?? getComputedBg(canvasEl)
        );
        const fileName = `${fileNamePrefix}-${timestamp()}.png`;
        downloadDataUrl(dataUrl, fileName);
        return fileName;
      } catch (fallbackErr) {
        this.toastService.error('Export failed. Try reducing graph size/zoom and retry.');
      }
    } finally {
      toggleExportingClass(canvasEl, false);
    }
  }
}
