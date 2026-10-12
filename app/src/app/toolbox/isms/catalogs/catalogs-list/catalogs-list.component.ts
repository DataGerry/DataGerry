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

import { Component, inject, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { Router } from '@angular/router';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { Column } from 'src/app/layout/table/table.types';
import { OscalCatalog, OscalCatalogManifest } from '../../models/oscal-catalog.model';
import { OscalCatalogService } from '../../services/oscal-catalog.service';

/**
 * Lists the OSCAL catalogs bundled with the frontend (BSI Stand der Technik, NIST) and
 * opens them in the bundled OSCAL viewer. The list is small and static, so search is client-side.
 */
@Component({
  selector: 'app-catalogs-list',
  templateUrl: './catalogs-list.component.html',
  styleUrls: ['./catalogs-list.component.scss'],
  standalone: false
})
export class CatalogsListComponent implements OnInit {
  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);
  private readonly catalogService = inject(OscalCatalogService);

  @ViewChild('titleTemplate', { static: true }) titleTemplate: TemplateRef<any>;
  @ViewChild('sizeTemplate', { static: true }) sizeTemplate: TemplateRef<any>;
  @ViewChild('licenseTemplate', { static: true }) licenseTemplate: TemplateRef<any>;
  @ViewChild('actionTemplate', { static: true }) actionTemplate: TemplateRef<any>;

  public manifest: OscalCatalogManifest | null = null;
  public catalogs: OscalCatalog[] = [];
  public filteredCatalogs: OscalCatalog[] = [];
  public loading = false;

  public columns: Column[] = [];
  public initialVisibleColumns: string[] = [];

  /* --------------------------------------------------- LIFECYCLE METHODS --------------------------------------------------- */

  ngOnInit(): void {
    this.setupColumns();
    this.loadCatalogs();
  }

  /* --------------------------------------------------- INIT --------------------------------------------------- */

  setupColumns(): void {
    this.columns = [
      {
        display: 'Title',
        name: 'title',
        data: 'title',
        searchable: false,
        sortable: false,
        template: this.titleTemplate,
        style: { width: 'auto' }
      },
      {
        display: 'Publisher',
        name: 'publisher',
        data: 'publisher',
        searchable: false,
        sortable: false,
        style: { width: '110px', 'text-align': 'center' }
      },
      {
        display: 'Version',
        name: 'version',
        data: 'version',
        searchable: false,
        sortable: false,
        style: { width: '150px', 'text-align': 'center' }
      },
      {
        display: 'Language',
        name: 'language',
        data: 'language',
        searchable: false,
        sortable: false,
        style: { width: '100px', 'text-align': 'center' }
      },
      {
        display: 'Controls',
        name: 'controls',
        data: 'controls',
        searchable: false,
        sortable: false,
        style: { width: '100px', 'text-align': 'center' }
      },
      {
        display: 'Size',
        name: 'size',
        data: 'size',
        searchable: false,
        sortable: false,
        template: this.sizeTemplate,
        style: { width: '100px', 'text-align': 'center' }
      },
      {
        display: 'License',
        name: 'license',
        data: 'license',
        searchable: false,
        sortable: false,
        template: this.licenseTemplate,
        style: { width: '180px', 'text-align': 'center' }
      },
      {
        display: 'Actions',
        name: 'actions',
        data: 'id',
        searchable: false,
        sortable: false,
        fixed: true,
        template: this.actionTemplate,
        style: { width: '110px', 'text-align': 'center' }
      }
    ];
    this.initialVisibleColumns = this.columns.map(c => c.name);
  }

  /* --------------------------------------------------- DATA --------------------------------------------------- */

  loadCatalogs(): void {
    this.loading = true;
    this.catalogService.getManifest().subscribe({
      next: (manifest) => {
        this.manifest = manifest;
        this.catalogs = manifest.catalogs ?? [];
        this.filteredCatalogs = this.catalogs;
        this.loading = false;
      },
      error: () => {
        this.loading = false;
        this.toast.error('The bundled catalog list could not be loaded.');
      }
    });
  }

  onSearchChange(search: string): void {
    const term = (search ?? '').trim().toLowerCase();
    this.filteredCatalogs = !term
      ? this.catalogs
      : this.catalogs.filter(c =>
          [c.title, c.publisher, c.version, c.language, c.license].some(v => (v ?? '').toLowerCase().includes(term))
        );
  }

  /* --------------------------------------------------- ACTIONS --------------------------------------------------- */

  onView(catalog: OscalCatalog): void {
    this.router.navigate(['/isms/catalogs/view', catalog.id]);
  }

  /** Opens the viewer as a standalone page in a new tab. */
  onOpenInNewTab(catalog: OscalCatalog): void {
    if (!this.manifest) {
      return;
    }

    window.open(this.catalogService.getViewerUrl(this.manifest, catalog), '_blank', 'noopener');
  }

  getDownloadUrl(catalog: OscalCatalog): string {
    return this.catalogService.toAbsoluteUrl(catalog.file);
  }

  getLicenseUrl(catalog: OscalCatalog): string {
    return this.catalogService.toAbsoluteUrl(catalog.licenseFile);
  }

  getFileName(catalog: OscalCatalog): string {
    return catalog.file.split('/').pop() ?? `${catalog.id}.json`;
  }

  formatSize(bytes: number): string {
    if (!bytes && bytes !== 0) {
      return '';
    }

    if (bytes < 1024 * 1024) {
      return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    }

    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
}
