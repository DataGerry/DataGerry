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

import { Component, DestroyRef, inject, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { combineLatest } from 'rxjs';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { OscalCatalog } from '../../models/oscal-catalog.model';
import { OscalCatalogService } from '../../services/oscal-catalog.service';

/**
 * Shows one bundled OSCAL catalog inside the bundled OSCAL viewer (embedded as an iframe,
 * both served from this application's own origin).
 */
@Component({
  selector: 'app-catalog-view',
  templateUrl: './catalog-view.component.html',
  styleUrls: ['./catalog-view.component.scss'],
  standalone: false
})
export class CatalogViewComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly sanitizer = inject(DomSanitizer);
  private readonly toast = inject(ToastService);
  private readonly catalogService = inject(OscalCatalogService);
  private readonly destroyRef = inject(DestroyRef);

  public catalog: OscalCatalog | null = null;
  public viewerUrl = '';
  public safeViewerUrl: SafeResourceUrl | null = null;
  public notFound = false;

  ngOnInit(): void {
    combineLatest([this.route.paramMap, this.catalogService.getManifest()])
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ([params, manifest]) => {
          const id = params.get('id');
          this.catalog = manifest.catalogs.find(c => c.id === id) ?? null;
          this.notFound = !this.catalog;

          if (this.catalog) {
            // The URL is built only from the bundled manifest (same-origin asset paths), never from user input,
            // so trusting it as a resource URL is safe.
            this.viewerUrl = this.catalogService.getViewerUrl(manifest, this.catalog);
            this.safeViewerUrl = this.sanitizer.bypassSecurityTrustResourceUrl(this.viewerUrl);
          } else {
            this.viewerUrl = '';
            this.safeViewerUrl = null;
          }
        },
        error: () => this.toast.error('The bundled catalog list could not be loaded.')
      });
  }

  onBack(): void {
    this.router.navigate(['/isms/catalogs']);
  }

  onOpenInNewTab(): void {
    if (this.viewerUrl) {
      window.open(this.viewerUrl, '_blank', 'noopener');
    }
  }

  getDownloadUrl(): string {
    return this.catalog ? this.catalogService.toAbsoluteUrl(this.catalog.file) : '';
  }

  getFileName(): string {
    return this.catalog?.file.split('/').pop() ?? '';
  }
}
