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

import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { AsyncPipe } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { FileSaverService } from 'ngx-filesaver';
import { combineLatest, finalize } from 'rxjs';

import { CoreModule } from 'src/app/core/core.module';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { OscalCatalog } from '../../models/oscal-catalog.model';
import { OscalCatalogService } from '../../services/oscal-catalog.service';

@Component({
  selector: 'app-catalog-view',
  templateUrl: './catalog-view.component.html',
  styleUrls: ['./catalog-view.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [AsyncPipe, CoreModule]
})
export class CatalogViewComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly sanitizer = inject(DomSanitizer);
  private readonly toast = inject(ToastService);
  private readonly loaderService = inject(LoaderService);
  private readonly catalogService = inject(OscalCatalogService);
  private readonly fileSaver = inject(FileSaverService);
  private readonly destroyRef = inject(DestroyRef);

  public readonly isLoading$ = this.loaderService.isLoading$;

  public readonly catalog = signal<OscalCatalog | null>(null);
  public readonly viewerUrl = signal('');
  public readonly safeViewerUrl = signal<SafeResourceUrl | null>(null);
  public readonly notFound = signal(false);

  /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

  ngOnInit(): void {
    this.loaderService.show();
    let loaderVisible = true;
    const hideLoader = (): void => {
      if (loaderVisible) {
        loaderVisible = false;
        this.loaderService.hide();
      }
    };

    combineLatest([this.route.paramMap, this.catalogService.getManifest()])
      .pipe(
        finalize(hideLoader),
        takeUntilDestroyed(this.destroyRef)
      )
      .subscribe({
        next: ([params, manifest]) => {
          hideLoader();
          const catalog = manifest.catalogs.find(entry => entry.id === params.get('id')) ?? null;
          this.catalog.set(catalog);
          this.notFound.set(!catalog);

          if (catalog) {
            this.viewerUrl.set(this.catalogService.getViewerUrl(manifest, catalog));
            // Built only from the bundled manifest (same-origin asset paths), never from user input.
            this.safeViewerUrl.set(this.sanitizer.bypassSecurityTrustResourceUrl(
              this.catalogService.getViewerUrl(manifest, catalog, true)
            ));
          } else {
            this.viewerUrl.set('');
            this.safeViewerUrl.set(null);
          }
        },
        error: () => this.toast.error('The bundled catalog list could not be loaded.')
      });
  }

  /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

  onBack(): void {
    this.router.navigate(['/isms/catalogs']);
  }

  onOpenInNewTab(): void {
    const url = this.viewerUrl();
    if (url) {
      window.open(url, '_blank', 'noopener');
    }
  }

  onDownload(): void {
    const catalog = this.catalog();
    if (!catalog) {
      return;
    }

    this.loaderService.show();
    this.catalogService.downloadCatalog(catalog)
      .pipe(
        finalize(() => this.loaderService.hide()),
        takeUntilDestroyed(this.destroyRef)
      )
      .subscribe({
        next: blob => this.fileSaver.save(blob, this.catalogService.getFileName(catalog)),
        error: () => this.toast.error('The catalog could not be downloaded.')
      });
  }
}
