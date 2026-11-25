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

import {
  ChangeDetectionStrategy,
  Component,
  computed,
  DestroyRef,
  inject,
  OnInit,
  signal,
  TemplateRef,
  viewChild
} from '@angular/core';
import { AsyncPipe, DecimalPipe } from '@angular/common';
import { Router, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { FileSaverService } from 'ngx-filesaver';
import { catchError, finalize, forkJoin, of, switchMap } from 'rxjs';

import { CoreModule } from 'src/app/core/core.module';
import { TableModule } from 'src/app/layout/table/table.module';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { Column } from 'src/app/layout/table/table.types';
import { ButtonTone } from 'src/app/core/components/base/button/app-button.types';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { CoreConfirmationModalComponent } from 'src/app/core/components/dialog/confirmation/core-confirmation-modal.component';
import { OscalCatalog, OscalCatalogManifest } from '../../models/oscal-catalog.model';
import { CatalogControlCounts } from '../../models/control-measure.model';
import { OscalCatalogService } from '../../services/oscal-catalog.service';
import { ControlMeasureService } from '../../services/control-measure.service';

interface CatalogRowTemplateContext {
  data: unknown;
  item: OscalCatalog;
}

@Component({
  selector: 'app-catalogs-list',
  templateUrl: './catalogs-list.component.html',
  styleUrls: ['./catalogs-list.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [AsyncPipe, DecimalPipe, RouterLink, CoreModule, TableModule]
})
export class CatalogsListComponent implements OnInit {
  private readonly titleTemplate = viewChild.required<TemplateRef<CatalogRowTemplateContext>>('titleTemplate');
  private readonly sizeTemplate = viewChild.required<TemplateRef<CatalogRowTemplateContext>>('sizeTemplate');
  private readonly versionTemplate = viewChild.required<TemplateRef<CatalogRowTemplateContext>>('versionTemplate');
  private readonly licenseTemplate = viewChild.required<TemplateRef<CatalogRowTemplateContext>>('licenseTemplate');
  private readonly actionTemplate = viewChild.required<TemplateRef<CatalogRowTemplateContext>>('actionTemplate');
  private readonly controlsTemplate = viewChild.required<TemplateRef<CatalogRowTemplateContext>>('controlsTemplate');
  private readonly importTemplate = viewChild.required<TemplateRef<CatalogRowTemplateContext>>('importTemplate');

  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);
  private readonly loaderService = inject(LoaderService);
  private readonly catalogService = inject(OscalCatalogService);
  private readonly controlMeasureService = inject(ControlMeasureService);
  private readonly permissionService = inject(PermissionService);
  private readonly modalService = inject(NgbModal);
  private readonly fileSaver = inject(FileSaverService);
  private readonly destroyRef = inject(DestroyRef);

  public readonly isLoading$ = this.loaderService.isLoading$;

  public readonly manifest = signal<OscalCatalogManifest | null>(null);
  public readonly catalogs = signal<OscalCatalog[]>([]);
  public readonly searchTerm = signal('');
  public readonly page = signal(1);
  public readonly pageSize = signal(10);
  public readonly loading = signal(false);
  /** Id of the catalog an import or delete is running for. */
  public readonly busyId = signal<string | null>(null);
  public readonly importedCounts = signal<CatalogControlCounts>({});

  public readonly filteredCatalogs = computed(() => {
    const term = this.searchTerm().trim().toLowerCase();
    if (!term) {
      return this.catalogs();
    }

    return this.catalogs().filter(catalog =>
      [catalog.title, catalog.publisher, catalog.version, catalog.language, catalog.license]
        .some(value => (value ?? '').toLowerCase().includes(term))
    );
  });

  public readonly pagedCatalogs = computed(() => {
    const start = (this.page() - 1) * this.pageSize();
    return this.filteredCatalogs().slice(start, start + this.pageSize());
  });

  public readonly canImport = this.hasRight('base.isms.controlMeasure.add');
  public readonly canDelete = this.hasRight('base.isms.controlMeasure.delete');

  public columns: Column[] = [];
  public initialVisibleColumns: string[] = [];

  /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

  ngOnInit(): void {
    this.setupColumns();
    this.loadCatalogs();
  }

  /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

  onSearchChange(search: string): void {
    this.searchTerm.set(search ?? '');
    this.page.set(1);
  }

  onPageChange(page: number): void {
    this.page.set(page);
  }

  onPageSizeChange(pageSize: number): void {
    this.pageSize.set(pageSize);
    this.page.set(1);
  }

  onView(catalog: OscalCatalog): void {
    this.router.navigate(['/isms/catalogs/view', catalog.id]);
  }

  onShowControls(catalog: OscalCatalog): void {
    this.router.navigate(['/isms/control-measures'], { queryParams: { catalog: catalog.id } });
  }

  onOpenInNewTab(catalog: OscalCatalog): void {
    const manifest = this.manifest();
    if (manifest) {
      window.open(this.catalogService.getViewerUrl(manifest, catalog), '_blank', 'noopener');
    }
  }

  onDownload(catalog: OscalCatalog): void {
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

  onImport(catalog: OscalCatalog): void {
    const count = this.importedCount(catalog);
    const update = count > 0;

    this.confirm({
      title: update ? 'Update controls from catalog' : 'Import requirements as controls',
      message: update
        ? `Update the ${count} controls imported from "${catalog.title}" with the current catalog?`
        : `Import the requirements of "${catalog.title}" (${catalog.controls} controls) as ISMS controls?`,
      note: update
        ? 'New requirements are added; title, chapter and description of changed ones are updated. Implementation ' +
          'state, applicability and reason are kept. Controls no longer in the catalog are reported, not deleted.'
        : 'The controls are created with the type "Requirement", the catalog as source and the implementation ' +
          'state "None". Running the import again later updates them.',
      confirmText: update ? 'Update' : 'Import',
      tone: 'brand'
    }).then(confirmed => confirmed && this.runImport(catalog, update));
  }

  onDeleteControls(catalog: OscalCatalog): void {
    this.confirm({
      title: 'Delete imported controls',
      message: `Delete the ${this.importedCount(catalog)} controls imported from "${catalog.title}"?`,
      note: 'Controls assigned to a risk assessment (control measure assignment) are kept and reported. ' +
        'Implementation state, applicability and reason of the deleted controls are lost.',
      confirmText: 'Delete',
      tone: 'danger'
    }).then(confirmed => confirmed && this.runDelete(catalog));
  }

  /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

  importedCount(catalog: OscalCatalog): number {
    return this.importedCounts()[catalog.id] ?? 0;
  }

  getLicenseUrl(catalog: OscalCatalog): string {
    return this.catalogService.toAbsoluteUrl(catalog.licenseFile);
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

  /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  private setupColumns(): void {
    this.columns = [
      this.column('Title', 'title', 'auto', this.titleTemplate(), 'left'),
      this.column('Publisher', 'publisher', '110px'),
      this.column('Version', 'version', '150px', this.versionTemplate()),
      this.column('Language', 'language', '100px'),
      this.column('Controls', 'controls', '100px', this.controlsTemplate()),
      { ...this.column('Imported', 'id', '200px', this.importTemplate()), name: 'imported' },
      this.column('Size', 'size', '100px', this.sizeTemplate()),
      this.column('License', 'license', '180px', this.licenseTemplate()),
      { ...this.column('Actions', 'id', '150px', this.actionTemplate()), name: 'actions', fixed: true }
    ];
    this.initialVisibleColumns = this.columns.map(column => column.name);
  }

  private column(
    display: string,
    data: string,
    width: string,
    template?: TemplateRef<CatalogRowTemplateContext>,
    align: 'left' | 'center' = 'center'
  ): Column {
    const style: Record<string, string> = { width };
    if (align === 'center') {
      style['text-align'] = 'center';
    }

    return { display, name: data, data, searchable: false, sortable: false, template, style };
  }

  private loadCatalogs(): void {
    this.loading.set(true);
    this.loaderService.show();

    forkJoin({
      manifest: this.catalogService.getManifest(),
      counts: this.controlMeasureService.getCatalogStatus().pipe(catchError(() => of({} as CatalogControlCounts)))
    })
      .pipe(
        finalize(() => {
          this.loading.set(false);
          this.loaderService.hide();
        }),
        takeUntilDestroyed(this.destroyRef)
      )
      .subscribe({
        next: ({ manifest, counts }) => {
          this.manifest.set(manifest);
          this.catalogs.set(manifest.catalogs ?? []);
          this.importedCounts.set(counts ?? {});
        },
        error: () => this.toast.error('The bundled catalog list could not be loaded.')
      });
  }

  private runImport(catalog: OscalCatalog, update: boolean): void {
    this.startBusy(catalog);

    this.catalogService.getImportControls(catalog)
      .pipe(
        switchMap(controls => this.controlMeasureService.importCatalog({
          catalog_id: catalog.id,
          catalog_title: catalog.title,
          controls
        })),
        finalize(() => this.stopBusy()),
        takeUntilDestroyed(this.destroyRef)
      )
      .subscribe({
        next: result => {
          const parts = [`${result.imported} added`];
          if (update) {
            parts.push(`${result.updated} updated`, `${result.unchanged} unchanged`);
          }
          this.toast.success(`"${catalog.title}": ${parts.join(', ')}.`);

          const obsolete = result.obsolete ?? [];
          if (obsolete.length) {
            const listed = obsolete.slice(0, 10).join(', ') + (obsolete.length > 10 ? ', ...' : '');
            this.toast.warning(`${obsolete.length} control(s) are no longer in the catalog and were kept: ${listed}`);
          }
          this.refreshCounts();
        },
        error: () => this.toast.error(`"${catalog.title}" could not be imported.`)
      });
  }

  private runDelete(catalog: OscalCatalog): void {
    this.startBusy(catalog);

    this.controlMeasureService.deleteCatalogControls(catalog.id)
      .pipe(
        finalize(() => this.stopBusy()),
        takeUntilDestroyed(this.destroyRef)
      )
      .subscribe({
        next: result => {
          this.toast.success(`${result.successfully.length} control(s) of "${catalog.title}" deleted.`);
          if (result.in_use?.length) {
            this.toast.warning(`${result.in_use.length} control(s) are assigned to a risk assessment and were kept.`);
          }
          this.refreshCounts();
        },
        error: () => this.toast.error(`The controls of "${catalog.title}" could not be deleted.`)
      });
  }

  private refreshCounts(): void {
    this.loaderService.show();
    this.controlMeasureService.getCatalogStatus()
      .pipe(
        finalize(() => this.loaderService.hide()),
        takeUntilDestroyed(this.destroyRef)
      )
      .subscribe({
        next: counts => this.importedCounts.set(counts ?? {}),
        error: () => this.toast.error('The number of imported controls could not be refreshed.')
      });
  }

  private startBusy(catalog: OscalCatalog): void {
    this.busyId.set(catalog.id);
    this.loaderService.show();
  }

  private stopBusy(): void {
    this.busyId.set(null);
    this.loaderService.hide();
  }

  private confirm(options: {
    title: string;
    message: string;
    note: string;
    confirmText: string;
    tone: ButtonTone;
  }): Promise<boolean> {
    const modalRef = this.modalService.open(CoreConfirmationModalComponent, {
      size: 'lg',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    const modal: CoreConfirmationModalComponent = modalRef.componentInstance;
    modal.title = options.title;
    modal.message = options.message;
    modal.warningTitle = 'Note:';
    modal.warningMessage = options.note;
    modal.confirmButtonText = options.confirmText;
    modal.confirmTone = options.tone;

    return modalRef.result.then(result => result === 'confirmed', () => false);
  }

  private hasRight(right: string): boolean {
    return this.permissionService.hasRight(right) || this.permissionService.hasExtendedRight(right);
  }
}
