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
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { catchError, finalize, forkJoin, of, switchMap } from 'rxjs';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { Column } from 'src/app/layout/table/table.types';
import { OscalCatalog, OscalCatalogManifest } from '../../models/oscal-catalog.model';
import { OscalCatalogService } from '../../services/oscal-catalog.service';
import { ControlMeasureService } from '../../services/control-measure.service';
import { CatalogControlCounts } from '../../models/control-measure.model';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { CoreConfirmationModalComponent } from 'src/app/core/components/dialog/confirmation/core-confirmation-modal.component';

/**
 * Lists the OSCAL catalogs bundled with the frontend (BSI Stand der Technik, NIST, NIS2, ISO/IEC 27001
 * Annex A) and opens them in the bundled OSCAL viewer. A catalog's requirements can be imported as
 * controls, updated from the catalog and deleted again. The list is small and static, so search is
 * client-side.
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
  private readonly controlMeasureService = inject(ControlMeasureService);
  private readonly permissionService = inject(PermissionService);
  private readonly modalService = inject(NgbModal);

  @ViewChild('titleTemplate', { static: true }) titleTemplate: TemplateRef<any>;
  @ViewChild('sizeTemplate', { static: true }) sizeTemplate: TemplateRef<any>;
  @ViewChild('licenseTemplate', { static: true }) licenseTemplate: TemplateRef<any>;
  @ViewChild('actionTemplate', { static: true }) actionTemplate: TemplateRef<any>;
  @ViewChild('importTemplate', { static: true }) importTemplate: TemplateRef<any>;

  public manifest: OscalCatalogManifest | null = null;
  public catalogs: OscalCatalog[] = [];
  public filteredCatalogs: OscalCatalog[] = [];
  public loading = false;
  /** id of the catalog being imported, updated or deleted, null when idle. */
  public busyId: string | null = null;
  /** Number of imported controls per catalog id. */
  public importedCounts: CatalogControlCounts = {};

  public readonly canImport = this.hasRight('base.isms.controlMeasure.add');
  public readonly canDelete = this.hasRight('base.isms.controlMeasure.delete');

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
        display: 'Imported',
        name: 'imported',
        data: 'id',
        searchable: false,
        sortable: false,
        template: this.importTemplate,
        style: { width: '230px', 'text-align': 'center' }
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
        style: { width: '130px', 'text-align': 'center' }
      }
    ];
    this.initialVisibleColumns = this.columns.map(c => c.name);
  }

  /* --------------------------------------------------- DATA --------------------------------------------------- */

  loadCatalogs(): void {
    this.loading = true;
    forkJoin({
      manifest: this.catalogService.getManifest(),
      counts: this.controlMeasureService.getCatalogStatus().pipe(catchError(() => of({} as CatalogControlCounts)))
    }).subscribe({
      next: ({ manifest, counts }) => {
        this.manifest = manifest;
        this.catalogs = manifest.catalogs ?? [];
        this.filteredCatalogs = this.catalogs;
        this.importedCounts = counts ?? {};
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

  /** Number of controls imported from the catalog. */
  importedCount(catalog: OscalCatalog): number {
    return this.importedCounts[catalog.id] ?? 0;
  }

  /**
   * Imports the requirements of the catalog as controls (type Requirement, linked to the catalog),
   * or - for an imported catalog - updates them from the catalog.
   */
  onImport(catalog: OscalCatalog): void {
    const update = this.importedCount(catalog) > 0;
    this.confirm(
      update ? 'Update controls from catalog' : 'Import requirements as controls',
      update
        ? `Update the ${this.importedCount(catalog)} controls imported from "${catalog.title}" with the current catalog?`
        : `Import the requirements of "${catalog.title}" (${catalog.controls} controls) as ISMS controls?`,
      update
        ? 'New requirements are added; title, chapter and description of changed ones are updated. Implementation ' +
          'state, applicability and reason are kept. Controls no longer in the catalog are reported, not deleted.'
        : 'The controls are created with the type "Requirement", the catalog as source and the implementation ' +
          'state "None". Running the import again later updates them.',
      update ? 'Update' : 'Import',
      'btn-primary'
    ).then(confirmed => confirmed && this.runImport(catalog, update));
  }

  private runImport(catalog: OscalCatalog, update: boolean): void {
    this.busyId = catalog.id;
    this.catalogService.getImportControls(catalog).pipe(
      switchMap(controls => this.controlMeasureService.importCatalog({
        catalog_id: catalog.id,
        catalog_title: catalog.title,
        controls
      })),
      finalize(() => this.busyId = null)
    ).subscribe({
      next: (result) => {
        const parts = [`${result.imported} added`];
        if (update) {
          parts.push(`${result.updated} updated`, `${result.unchanged} unchanged`);
        }
        this.toast.success(`"${catalog.title}": ${parts.join(', ')}.`);
        if (result.obsolete?.length) {
          this.toast.warning(
            `${result.obsolete.length} control(s) are no longer in the catalog and were kept: ` +
            `${result.obsolete.slice(0, 10).join(', ')}${result.obsolete.length > 10 ? ', ...' : ''}`
          );
        }
        this.refreshCounts();
      },
      error: (err) => this.toast.error(err?.error?.message ?? 'The catalog could not be imported.')
    });
  }

  /** Deletes the controls imported from the catalog; controls assigned to a risk assessment are kept. */
  onDeleteControls(catalog: OscalCatalog): void {
    this.confirm(
      'Delete imported controls',
      `Delete the ${this.importedCount(catalog)} controls imported from "${catalog.title}"?`,
      'Controls assigned to a risk assessment (control measure assignment) are kept and reported. ' +
      'Implementation state, applicability and reason of the deleted controls are lost.',
      'Delete',
      'btn-danger'
    ).then(confirmed => {
      if (!confirmed) {
        return;
      }
      this.busyId = catalog.id;
      this.controlMeasureService.deleteCatalogControls(catalog.id)
        .pipe(finalize(() => this.busyId = null))
        .subscribe({
          next: (result) => {
            this.toast.success(`${result.successfully.length} control(s) of "${catalog.title}" deleted.`);
            if (result.in_use?.length) {
              this.toast.warning(`${result.in_use.length} control(s) are assigned to a risk assessment and were kept.`);
            }
            this.refreshCounts();
          },
          error: (err) => this.toast.error(err?.error?.message ?? 'The controls could not be deleted.')
        });
    });
  }

  private refreshCounts(): void {
    this.controlMeasureService.getCatalogStatus().subscribe({
      next: (counts) => this.importedCounts = counts ?? {},
      error: () => { /* the counts are informative only */ }
    });
  }

  private confirm(title: string, message: string, note: string, button: string, buttonClass: string): Promise<boolean> {
    const modalRef = this.modalService.open(CoreConfirmationModalComponent, {
      size: 'lg',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    modalRef.componentInstance.title = title;
    modalRef.componentInstance.message = message;
    modalRef.componentInstance.warningTitle = 'Note:';
    modalRef.componentInstance.warningMessage = note;
    modalRef.componentInstance.confirmButtonText = button;
    modalRef.componentInstance.confirmButtonClass = buttonClass;

    return modalRef.result.then(result => result === 'confirmed', () => false);
  }

  private hasRight(right: string): boolean {
    return this.permissionService.hasRight(right) || this.permissionService.hasExtendedRight(right);
  }

  /** Opens the controls of this catalog. */
  onShowControls(catalog: OscalCatalog): void {
    this.router.navigate(['/isms/control-measures'], { queryParams: { catalog: catalog.id } });
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
