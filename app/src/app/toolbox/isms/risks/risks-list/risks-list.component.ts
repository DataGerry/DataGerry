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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import {
  Component,
  inject,
  OnInit,
  TemplateRef,
  ViewChild,
} from '@angular/core';
import { Router } from '@angular/router';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { finalize } from 'rxjs/operators';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { FilterBuilderService } from 'src/app/core/services/filter-builder.service';
import { CoreDeleteConfirmationModalComponent } from 'src/app/core/components/dialog/delete-dialog/core-delete-confirmation-modal.component';

import { Risk } from 'src/app/toolbox/isms/models/risk.model';
import { RiskService } from 'src/app/toolbox/isms/services/risk.service';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { Column, Sort, SortDirection } from 'src/app/layout/table/table.types';
import { ExtendableOptionService } from '../../services/extendable-option.service';
import { OptionType } from '../../models/option-type.enum';
import { ExtendableOption } from 'src/app/framework/models/object-group.model';

@Component({
    selector: 'app-risks-list',
    templateUrl: './risks-list.component.html',
    styleUrls: ['./risks-list.component.scss'],
    standalone: false
})
export class RisksListComponent implements OnInit {
  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);
  private readonly loaderService = inject(LoaderService);
  private readonly modalService = inject(NgbModal);
  private readonly filterBuilderService = inject(FilterBuilderService);
  private readonly riskService = inject(RiskService);
  private readonly extendableOptionService = inject(ExtendableOptionService);

  // Template references for the cmdb-table
  @ViewChild('actionTemplate', { static: true }) actionTemplate: TemplateRef<any>;
  @ViewChild('riskTypeTemplate', { static: true }) riskTypeTemplate: TemplateRef<any>;
  @ViewChild('categoryTemplate', { static: true }) categoryTemplate: TemplateRef<any>;

  // Data
  public risks: Risk[] = [];
  public totalRisks = 0;

  public categoryOptions: ExtendableOption[] = [];


  // Table options
  public page = 1;
  public limit = 10;
  public loading = false;
  public filter = '';
  public sort: Sort = { name: 'public_id', order: SortDirection.DESCENDING };
  public columns: Column[] = [];
  public initialVisibleColumns: string[] = [];

  ngOnInit(): void {
    this.setupColumns();
    this.loadCategoryOptions();
    this.loadRisks();
  }

  /**
   * Define our table columns
   */
  setupColumns(): void {
    this.columns = [
      {
        display: 'Public ID',
        name: 'public_id',
        data: 'public_id',
        searchable: false,
        sortable: true,
        style: { width: '120px', 'text-align': 'center' }
      },
      {
        display: 'Name',
        name: 'name',
        data: 'name',
        searchable: true,
        sortable: true,
        style: { width: 'auto' },
        cssClasses: ['text-center'],
      },
      {
        display: 'Identifier',
        name: 'identifier',
        data: 'identifier',
        searchable: true,
        sortable: true,
        style: { width: '150px', 'text-align': 'center' }
      },
      // {
      //   display: 'Risk Type',
      //   name: 'risk_type',
      //   data: 'risk_type',
      //   searchable: true,
      //   sortable: true,
      //   template: this.riskTypeTemplate,
      //   style: { width: '150px', 'text-align': 'center' }
      // },
      {
        display: 'Category',
        name: 'category_id',
        data: 'category_id',
        searchable: true,
        sortable: false,
        template: this.categoryTemplate,
        style: { width: '150px', 'text-align': 'center' }
      },
      {
        display: 'Actions',
        name: 'actions',
        data: 'public_id',
        searchable: false,
        sortable: false,
        fixed: true,
        template: this.actionTemplate,
        style: { width: '120px', 'text-align': 'center' }
      }
    ];
    this.initialVisibleColumns = this.columns.map((c) => c.name);
  }


  /**
   * Load the data from backend
   */
  loadRisks(): void {
    this.loading = true;
    this.loaderService.show();

    const filterQuery = this.filterBuilderService.buildFilter(
      this.filter,
      [{ name: 'public_id' }, { name: 'name' }, { name: 'identifier' }, { name: 'risk_type' }]
    );

    const params: CollectionParameters = {
      filter: filterQuery,
      limit: this.limit,
      page: this.page,
      sort: this.sort.name,
      order: this.sort.order
    };

    this.riskService.getRisks(params)
      .pipe(finalize(() => {
        this.loading = false;
        this.loaderService.hide();
      }))
      .subscribe({
        next: (resp) => {
          this.risks = resp.results;
          this.totalRisks = resp.total;
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }


  /**
 * Load category options from backend
 */
  private loadCategoryOptions(): void {
    this.extendableOptionService.getExtendableOptionsByType(OptionType.RISK)
      .subscribe({
        next: (res) => {
          this.categoryOptions = res.results || [];
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }




  /**
   * Create a new Risk
   */
  onAddNew(): void {
    this.router.navigate(['/isms/risks/add']);
  }

  /**
   * View Risk
   */
  onView(risk: Risk): void {
    this.router.navigate(
      ['/isms/risks/view'],
      { state: { risk } }
    );
  }


  /**
   * Edit Risk
   */
  onEdit(risk: Risk): void {
    this.router.navigate(
      ['/isms/risks/edit'],
      { state: { risk } }
    );
  }


  /**
   * Delete Risk (show confirmation modal)
   */
  onDelete(risk: Risk): void {
    if (!risk.public_id) {
      return;
    }
    const modalRef = this.modalService.open(CoreDeleteConfirmationModalComponent, { size: 'lg' });
    modalRef.componentInstance.title = 'Delete Risk';
    modalRef.componentInstance.item = risk;
    modalRef.componentInstance.itemType = 'Risk';
    modalRef.componentInstance.itemName = risk.name;
    modalRef.componentInstance.warningTitle = 'Warning:';
    modalRef.componentInstance.warningMessage = `Deleting this Risk will also permanently remove all associated Risk Assessments. This action cannot be undone!`;
    modalRef.componentInstance.warningIconClass = 'fas fa-exclamation-triangle';

    modalRef.result.then(
      (result) => {
        if (result === 'confirmed') {
          this.loaderService.show();
          this.riskService.deleteRisk(risk.public_id)
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
              next: () => {
                this.toast.success('Risk deleted successfully.');
                this.loadRisks();
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

  /**
 * Returns category name from its id.
 */
  getCategoryName(categoryId: number): string {
    const option = this.categoryOptions.find(opt => opt.public_id === categoryId);
    return option?.value || '';
  }


  /* ------------------------------------------------------------
   * Pagination, sorting, search handlers
   * ------------------------------------------------------------
   */

  onPageChange(page: number): void {
    this.page = page;
    this.loadRisks();
  }

  onPageSizeChange(limit: number): void {
    this.limit = limit;
    this.page = 1;
    this.loadRisks();
  }

  onSortChange(sort: Sort): void {
    this.sort = sort;
    this.loadRisks();
  }

  onSearchChange(search: string): void {
    this.filter = search;
    this.page = 1;
    this.loadRisks();
  }
}
