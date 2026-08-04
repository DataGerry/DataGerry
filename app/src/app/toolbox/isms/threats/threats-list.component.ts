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
import { finalize } from 'rxjs/operators';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { FilterBuilderService } from 'src/app/core/services/filter-builder.service';
import { CoreDeleteConfirmationModalComponent } from 'src/app/core/components/dialog/delete-dialog/core-delete-confirmation-modal.component';



import { Column, Sort, SortDirection } from 'src/app/layout/table/table.types';
import { ExtendableOptionService } from 'src/app/toolbox/isms/services/extendable-option.service';
import { OptionType } from 'src/app/toolbox/isms/models/option-type.enum';
import { Threat, ThreatBulkDeleteResult } from '../models/threat.model';
import { ExtendableOption } from 'src/app/framework/models/object-group.model';
import { ThreatService } from '../services/threat.service';

@Component({
    selector: 'app-threats-list',
    templateUrl: './threats-list.component.html',
    styleUrls: ['./threats-list.component.scss'],
    standalone: false
})
export class ThreatsListComponent implements OnInit {
  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);
  private readonly loaderService = inject(LoaderService);
  private readonly threatService = inject(ThreatService);
  private readonly modalService = inject(NgbModal);
  private readonly filterBuilderService = inject(FilterBuilderService);
  private readonly extendableOptionService = inject(ExtendableOptionService);

  @ViewChild('actionTemplate', { static: true }) actionTemplate: TemplateRef<any>;
  @ViewChild('sourceTemplate', { static: true }) sourceTemplate: TemplateRef<any>;

  public threats: Threat[] = [];
  public totalThreats = 0;

  // Threats currently selected in the table for bulk actions
  public selectedThreats: Threat[] = [];

  public page = 1;
  public limit = 10;
  public loading = false;
  public filter = '';
  public sort: Sort = { name: 'public_id', order: SortDirection.ASCENDING };

  // Table columns
  public columns: Column[] = [];
  public initialVisibleColumns: string[] = [];

  // For showing source names
  public sourceOptions: ExtendableOption[] = [];

  /* --------------------------------------------------- LIFECYCLE MEHTODS --------------------------------------------------- */

  ngOnInit(): void {
    this.setupColumns();
    this.loadSourceOptions();
    this.loadThreats();
  }

  /* --------------------------------------------------- INIT --------------------------------------------------- */

  /* 
  * Define table columns and templates
  */
  setupColumns(): void {
    this.columns = [
      {
        display: 'Public ID',
        name: 'public_id',
        data: 'public_id',
        searchable: false,
        sortable: false,
        style: { width: '120px', 'text-align': 'center' }
      },
      {
        display: 'Name',
        name: 'name',
        data: 'name',
        searchable: false,
        sortable: false,
        style: { width: 'auto' },
        cssClasses: ['text-center'],

      },
      {
        display: 'Identifier',
        name: 'identifier',
        data: 'identifier',
        searchable: false,
        sortable: false,
        style: { width: '180px', 'text-align': 'center' }
      },
      {
        display: 'Source',
        name: 'source',
        data: 'source',
        searchable: false,
        sortable: false,
        template: this.sourceTemplate,
        style: { width: 'auto' },
        cssClasses: ['text-center']
      },
      {
        display: 'Actions',
        name: 'actions',
        data: 'public_id',
        searchable: false,
        sortable: false,
        fixed: true,
        template: this.actionTemplate,
        style: { width: '80px', 'text-align': 'center' }
      }
    ];
    this.initialVisibleColumns = this.columns.map(c => c.name);
  }


  /* --------------------------------------------------- API CALLS --------------------------------------------------- */

  /*
  * Load the source options
  */
  loadSourceOptions(): void {
    this.loaderService.show();
    this.extendableOptionService.getExtendableOptionsByType(OptionType.THREAT_VULNERABILITY)
      .pipe(finalize(() => this.loaderService.hide()))
      .subscribe({
        next: (res) => {
          this.sourceOptions = res.results;
        },
        error: (err) => this.toast.error(err?.error?.message)
      });
  }

  /*
  * Load the threats from the backend
  */
  loadThreats(): void {
    this.loading = true;
    this.loaderService.show();

    const filterQuery = this.filterBuilderService.buildFilter(
      this.filter,
      [{ name: 'public_id' }, { name: 'name' }, { name: 'identifier' }]
    );

    const params: CollectionParameters = {
      filter: filterQuery,
      limit: this.limit,
      page: this.page,
      sort: this.sort.name,
      order: this.sort.order
    };

    this.threatService.getThreats(params)
      .pipe(finalize(() => {
        this.loading = false;
        this.loaderService.hide();
      }))
      .subscribe({
        next: (resp) => {
          this.threats = resp.results;
          this.totalThreats = resp.total;
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }

  /* --------------------------------------------------- ACTIONS--------------------------------------------------- */

  /*
  * Add a new threat
  */
  onAddNew(): void {
    this.router.navigate(['/isms/threats/add']);
  }

  /*
  * Edit a threat
  */
  onEdit(threat: Threat): void {
    if (threat.public_id) {
      this.router.navigate(['/isms/threats/edit', threat.public_id]);
    }
  }

  /*
* View a new threat
*/
  onView(threat: Threat): void {
    this.router.navigate(
      ['/isms/threats/view'],
      { state: { threat } }
    );
  }

  /*
  * Delete a threat
  */
  onDelete(threat: Threat): void {
    const modalRef = this.modalService.open(CoreDeleteConfirmationModalComponent, {
      size: 'lg',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    modalRef.componentInstance.title = 'Delete Threat';
    modalRef.componentInstance.item = threat;
    modalRef.componentInstance.itemType = 'Threat';
    modalRef.componentInstance.itemName = threat.name;

    modalRef.result.then(
      (result) => {
        if (result === 'confirmed' && threat.public_id) {
          this.loaderService.show();
          this.threatService.deleteThreat(threat.public_id)
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
              next: () => {
                this.toast.success('Threat deleted successfully.');
                this.loadThreats();
              },
              error: (err) => {
                this.toast.error(err?.error?.message);
              }
            });
        }
      },
      () => { }
    );
  }


  /*
  * Keep track of the threats selected in the table.
  */
  onSelectedChange(selected: Threat[]): void {
    this.selectedThreats = selected ?? [];
  }


  /*
  * Delete all currently selected threats. Threats that are still assigned to a
  * Risk are reported back as skipped.
  */
  onDeleteSelected(): void {
    const publicIds = this.selectedThreats
      .map((threat) => threat.public_id)
      .filter((id): id is number => id != null);

    if (!publicIds.length) {
      return;
    }

    const isPlural = publicIds.length > 1;
    const modalRef = this.modalService.open(CoreDeleteConfirmationModalComponent, {
      size: 'lg',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    modalRef.componentInstance.title = 'Delete Threats';
    modalRef.componentInstance.item = this.selectedThreats;
    modalRef.componentInstance.itemType = 'Threats';
    modalRef.componentInstance.itemName = `${publicIds.length} selected Threat${isPlural ? 's' : ''}`;
    modalRef.componentInstance.warningMessage =
      'Threats assigned to a Risk cannot be deleted and will be skipped.';

    modalRef.result.then(
      (result) => {
        if (result !== 'confirmed') {
          return;
        }
        this.loaderService.show();
        this.threatService.deleteThreats(publicIds)
          .pipe(finalize(() => this.loaderService.hide()))
          .subscribe({
            next: (response) => {
              this.notifyBulkDeleteResult(response);
              this.selectedThreats = [];
              this.loadThreats();
            },
            error: (err) => {
              this.toast.error(err?.error?.message);
            }
          });
      },
      () => { }
    );
  }


  /* --------------------------------------------------- Pagination, sorting, and search handlers --------------------------------------------------- */


  onPageChange(page: number): void {
    this.selectedThreats = [];
    this.page = page;
    this.loadThreats();
  }

  onPageSizeChange(limit: number): void {
    this.selectedThreats = [];
    this.limit = limit;
    this.page = 1;
    this.loadThreats();
  }

  onSortChange(sort: Sort): void {
    this.selectedThreats = [];
    this.sort = sort;
    this.loadThreats();
  }

  onSearchChange(search: string): void {
    this.selectedThreats = [];
    this.filter = search;
    this.page = 1;
    this.loadThreats();
  }

  /*
* Get the source name by its public_id
*/
  getSourceNames(sourceIds: number): string {
    const option = this.sourceOptions.find(opt => opt?.public_id === sourceIds);
    return option?.value;
  }

  /* --------------------------------------------------- PRIVATE FUNCTIONS --------------------------------------------------- */

  /*
  * Surface the outcome of a bulk delete: how many threats were removed and which
  * ones were skipped because they are still assigned to a Risk.
  */
  private notifyBulkDeleteResult(result: ThreatBulkDeleteResult): void {
    const deletedCount = result?.successfully?.length ?? 0;
    const inUseIds = result?.in_use ?? [];

    if (deletedCount > 0) {
      this.toast.success(`${deletedCount} Threat${deletedCount > 1 ? 's' : ''} deleted successfully.`);
    }

    if (inUseIds.length) {
      const names = inUseIds.map((id) => this.getThreatName(id)).join(', ');
      const isPlural = inUseIds.length > 1;
      this.toast.warning(
        `${inUseIds.length} Threat${isPlural ? 's' : ''} could not be deleted because ` +
        `${isPlural ? 'they are' : 'it is'} assigned to a Risk: ${names}.`
      );
    }
  }


  /*
  * Resolve a threat's display name by its public id, falling back to the id.
  */
  private getThreatName(publicId: number): string {
    const threat = this.threats.find((item) => item.public_id === publicId);
    return threat?.name ?? `#${publicId}`;
  }
}
