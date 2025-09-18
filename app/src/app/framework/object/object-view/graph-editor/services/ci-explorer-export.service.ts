import { Injectable } from '@angular/core';


export interface CiExportPngOptions {
 fileNamePrefix?: string;      // default: 'ci-explorer'
 backgroundColor?: string;     // default: computed bg or white
 currentZoom?: number;         // used by viewport export for crispness
 pixelRatioMax?: number;       // cap DPR multiplier (default: 3)
 padding?: number;             // extra px around content (default: 24)
}


@Injectable({ providedIn: 'root' })
export class CiExplorerExportService {
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


   await this.waitForFonts();
   this.toggleExportingClass(viewportEl, true);


   const baseDpr = Math.max(1, window.devicePixelRatio || 1);
   const suggested = baseDpr / (currentZoom || 1);
   const pixelRatio = this.clamp(suggested, 1, pixelRatioMax);


   const fileName = `${fileNamePrefix}-${this.timestamp()}.png`;


  try {
    const { toSvg } = await import('html-to-image');
    // Render to SVG first to preserve SVG paths/markers reliably
    const svgString = await toSvg(viewportEl, {
      cacheBust: true,
      pixelRatio,
      backgroundColor: backgroundColor ?? this.getComputedBg(viewportEl),
    });

    const dataUrl = await this.svgStringToPngDataUrl(
      svgString,
      viewportEl.clientWidth,
      viewportEl.clientHeight,
      pixelRatio,
      backgroundColor ?? this.getComputedBg(viewportEl)
    );

    this.downloadDataUrl(dataUrl, fileName);
    return fileName;
   } catch (err) {
     console.error('[CI Export] Viewport PNG export failed:', err);
     throw new Error('Export failed. Try reducing graph size/zoom and retry.');
   } finally {
     this.toggleExportingClass(viewportEl, false);
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
    if (!canvasEl) throw new Error('[CI Export] canvas element is missing.');
    const {
      fileNamePrefix = 'ci-explorer',
      backgroundColor,
      pixelRatioMax = 3,
      padding = 50
    } = opts;

    await this.waitForFonts();
    this.toggleExportingClass(canvasEl, true);

    // 1) Measure content bounds and add small safety pad to prevent arrow clipping
    const BBOX_PAD = 16;
    const b = this.computeContentBounds(canvasEl);
    const minX = Math.floor(b.minX) - BBOX_PAD;
    const minY = Math.floor(b.minY) - BBOX_PAD;
    const exportWidth  = Math.ceil(b.width  + padding * 2) + BBOX_PAD * 2;
    const exportHeight = Math.ceil(b.height + padding * 2) + BBOX_PAD * 2;

    // 2) Compute safe pixel ratio within megapixel cap
    const baseDpr = Math.max(1, window.devicePixelRatio || 1);
    let pixelRatio = this.clamp(baseDpr, 1, pixelRatioMax);
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
      ctx.fillStyle = backgroundColor ?? this.getComputedBg(canvasEl);
      ctx.fillRect(0, 0, exportWidth, exportHeight);

      // Draw connections as pure SVG image
      // IMPORTANT: for export reliability, flatten gradient strokes to a solid color
      const svgString = this.buildShiftedConnectionsSvg(svgEl, exportWidth, exportHeight, translateX, translateY, true);
      const svgUrl = URL.createObjectURL(new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' }));
      const svgImg = await this.loadImage(svgUrl);
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
      const nodesImg = await this.loadImage(nodesPngUrl);
      ctx.drawImage(nodesImg, 0, 0, exportWidth, exportHeight);

      const fileName = `${fileNamePrefix}-${this.timestamp()}.png`;
      this.downloadDataUrl(canvas.toDataURL('image/png'), fileName);
      return fileName;
    } catch (primaryErr) {
      // console.warn('[CI Export] Composite failed, falling back to single toSvg → PNG.', primaryErr);
      try {
        const { toSvg } = await import('html-to-image');
        const svgString = await toSvg(canvasEl, {
          cacheBust: true,
          width: exportWidth,
          height: exportHeight,
          pixelRatio,
          backgroundColor: backgroundColor ?? this.getComputedBg(canvasEl),
          style: {
            transform: `translate(${translateX}px, ${translateY}px) scale(1)`,
            transformOrigin: 'top left',
          },
        });
        const dataUrl = await this.svgStringToPngDataUrl(
          svgString,
          exportWidth,
          exportHeight,
          pixelRatio,
          backgroundColor ?? this.getComputedBg(canvasEl)
        );
        const fileName = `${fileNamePrefix}-${this.timestamp()}.png`;
        this.downloadDataUrl(dataUrl, fileName);
        return fileName;
      } catch (fallbackErr) {
        // console.error('[CI Export] Full-canvas export failed (composite and fallback).', fallbackErr);
        throw new Error('Export failed. See console for details.');
      }
    } finally {
      this.toggleExportingClass(canvasEl, false);
    }
 }






 // ------------------ bounds & helpers ------------------


 /** Measure min/max extents from positioned nodes and SVG connection group. */
 private computeContentBounds(canvasEl: HTMLElement): {
   minX: number; minY: number; maxX: number; maxY: number; width: number; height: number;
 } {
   let minX = Number.POSITIVE_INFINITY;
   let minY = Number.POSITIVE_INFINITY;
   let maxX = Number.NEGATIVE_INFINITY;
   let maxY = Number.NEGATIVE_INFINITY;


   // Nodes (absolutely positioned inside .nodes-container)
   const nodeEls = Array.from(canvasEl.querySelectorAll<HTMLElement>('.nodes-container .ci-node'));
   for (const el of nodeEls) {
     const left = this.readPx(el.style.left, el.offsetLeft);
     const top  = this.readPx(el.style.top,  el.offsetTop);
     const w = el.offsetWidth  || el.clientWidth  || 0;
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


 private readPx(styleValue: string, fallback: number): number {
   if (!styleValue) return fallback || 0;
   const n = parseFloat(styleValue);
   return isNaN(n) ? (fallback || 0) : n;
 }


 private async waitForFonts(): Promise<void> {
   const f: any = (document as any).fonts;
   if (f?.ready) {
     try { await f.ready; } catch { /* no-op */ }
   }
 }


 private getComputedBg(el: HTMLElement): string {
   const bg = getComputedStyle(el).backgroundColor;
   return (!bg || bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent') ? '#ffffff' : bg;
 }


 private downloadDataUrl(dataUrl: string, fileName: string): void {
   const a = document.createElement('a');
   a.href = dataUrl;
   a.download = fileName;
   a.rel = 'noopener';
   document.body.appendChild(a);
   a.click();
   document.body.removeChild(a);
 }


 private timestamp(): string {
   const d = new Date();
   const pad = (n: number) => String(n).padStart(2, '0');
   return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
   }


 private clamp(v: number, min: number, max: number): number {
   return Math.max(min, Math.min(max, v));
 }


 /** Freeze animations/transitions during capture for stability. */
 private toggleExportingClass(el: HTMLElement, on: boolean): void {
   const cls = 'ci-exporting';
   on ? el.classList.add(cls) : el.classList.remove(cls);
 }


  /** Build a CLEAN SVG from the live .connections-svg and shift its content so nothing gets clipped. */
  private buildShiftedConnectionsSvg(
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

  /** Promise-based image loader (use for both SVG and PNG data URLs). */
  private loadImage(url: string): Promise<HTMLImageElement> {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error('Image load failed'));
      img.src = url;
    });
  }

  /** Convert an SVG markup string into a PNG data URL at the given dimensions. */
  private async svgStringToPngDataUrl(
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
      const img = await this.loadImage(url);
      ctx.drawImage(img, 0, 0, width, height);
      return canvas.toDataURL('image/png');
    } finally {
      URL.revokeObjectURL(url);
    }
  }
}