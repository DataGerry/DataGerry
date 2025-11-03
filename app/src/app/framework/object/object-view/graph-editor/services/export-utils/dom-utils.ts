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

export async function waitForFonts(): Promise<void> {
  const f: any = (document as any).fonts;
  if (f?.ready) {
    try { await f.ready; } catch { /* no-op */ }
  }
}

export function getComputedBg(el: HTMLElement): string {
  const bg = getComputedStyle(el).backgroundColor;
  return (!bg || bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent') ? '#ffffff' : bg;
}

export function downloadDataUrl(dataUrl: string, fileName: string): void {
  const a = document.createElement('a');
  a.href = dataUrl;
  a.download = fileName;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

/** Freeze animations/transitions during capture for stability. */
export function toggleExportingClass(el: HTMLElement, on: boolean): void {
  const cls = 'ci-exporting';
  on ? el.classList.add(cls) : el.classList.remove(cls);
}
