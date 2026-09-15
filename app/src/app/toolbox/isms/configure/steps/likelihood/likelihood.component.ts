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
import { Component, inject, EventEmitter, Input, OnInit, Output, TemplateRef, ViewChild } from '@angular/core';
import { finalize } from 'rxjs/operators';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { CoreDeleteConfirmationModalComponent } from 'src/app/core/components/dialog/delete-dialog/core-delete-confirmation-modal.component';
import { Likelihood } from '../../../models/likelihood.model';
import { LikelihoodService } from '../../../services/likelihood.service';
import { LikelihoodModalComponent } from './modal/likelihood-modal.component';
import { IsmsConfig } from '../../../models/isms-config.model';
import { Sort, SortDirection } from 'src/app/layout/table/table.types';

@Component({
    selector: 'app-isms-likelihood',
    templateUrl: './likelihood.component.html',
    styleUrls: ['./likelihood.component.scss'],
    standalone: false
})
export class LikelihoodsComponent implements OnInit {
  private readonly likelihoodService = inject(LikelihoodService);
  private readonly toast = inject(ToastService);
  private readonly modalService = inject(NgbModal);
  private readonly loaderService = inject(LoaderService);

  public likelihoods: Likelihood[] = [];
  public totalLikelihoods = 0;
  public page = 1;
  public limit = 10;
  public loading = false;
  public defaultCalculationBasis: number = -Infinity;

  @ViewChild('actionsTemplate', { static: true }) actionsTemplate: TemplateRef<any>;

  @Input() config: IsmsConfig;
  @Output() likelihoodCountChange = new EventEmitter<number>();


  public columns: Array<any>;
  public sort: Sort = { name: 'calculation_basis', order: SortDirection.DESCENDING } as Sort;

  public isLoading$ = this.loaderService.isLoading$;

  ngOnInit(): void {
    this.columns = [
      // {
      //   display: 'Public ID',
      //   name: 'publicId',
      //   data: 'public_id',
      //   searchable: false,
      //   sortable: false,
      //   style: { width: '90px', 'text-align': 'center' }
      // },
      {
        display: 'Name',
        name: 'name',
        data: 'name',
        sortable: false,
        style: { width: 'auto'},
        cssClasses: ['text-center'],

      },
      {
        display: 'Calculation Basis',
        name: 'calculation_basis',
        data: 'calculation_basis',
        sortable: false,
        style: { width: '160px', 'text-align': 'center' }
      },
      {
        display: 'Description',
        name: 'description',
        data: 'description',
        sortable: false,
        style: { width: 'auto' },
        cssClasses: ['text-center'],

      },
      {
        display: 'Actions',
        name: 'actions',
        template: this.actionsTemplate,
        sortable: false,
        style: { width: '80px', 'text-align': 'center' }
      }
    ];

    this.loadLikelihoods();
  }

  
  /**
   * Loads likelihoods from the backend with pagination and sorting.
   */
  private loadLikelihoods(): void {
    this.loading = true;
    this.loaderService.show();

    this.likelihoodService
      .getLikelihoods({
        filter: '',
        limit: this.limit,
        page: this.page,
        sort: this.sort.name,
        order: this.sort.order
      })
      .pipe(
        finalize(() => {
          this.loaderService.hide();
          this.loading = false;
        })
      )
      .subscribe({
        next: (data) => {
          this.likelihoods = data.results;
          this.totalLikelihoods = data.total;

          this.likelihoodCountChange.emit(this.likelihoods.length);

        },
        error: (err) => {
          this.likelihoods = [];
          this.totalLikelihoods = 0;
          this.likelihoodCountChange.emit(0);
          this.toast.error(err?.error?.message);
        }
      });
  }


  /**
   * Opens add likelihood modal.
   */
  public addLikelihood(): void {
    const maxBasis = Math.max(...this.likelihoods.map(o => Number(o.calculation_basis)));

    // Set defaultCalculationBasis to 1 if maxBasis is -Infinity, otherwise increment maxBasis
    if (maxBasis === -Infinity) {
      this.defaultCalculationBasis = 1;
    } else if (Number.isInteger(maxBasis)) {
      this.defaultCalculationBasis = maxBasis + 1;
    } else {
      // Don't assign defaultCalculationBasis if it's a decimal
      this.defaultCalculationBasis = undefined;
    }    
    const modalRef = this.modalService.open(LikelihoodModalComponent, {
      size: 'lg',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    modalRef.componentInstance.existingCalculationBases = this.likelihoods.map(i => parseFloat(i.calculation_basis as any));
    modalRef.componentInstance.defaultCalculationBasis = this.defaultCalculationBasis;
    // No input => add mode
    modalRef.result.then(
      (result) => {
        if (result === 'saved') {
          this.loadLikelihoods();
        }
      },
      () => { }
    );
  }


  /**
   * Opens edit likelihood modal with pre-filled data.
   */
  public editLikelihood(item: Likelihood): void {
    const modalRef = this.modalService.open(LikelihoodModalComponent, {
      size: 'lg',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    modalRef.componentInstance.likelihood = { ...item };
    modalRef.result.then(
      (result) => {
        if (result === 'saved') {
          this.loadLikelihoods();
        }
      },
      () => { }
    );
  }


  /**
   * Opens delete confirmation modal and deletes the likelihood on confirm.
   */
  public deleteLikelihood(item: Likelihood): void {
    const modalRef = this.modalService.open(CoreDeleteConfirmationModalComponent, {
      size: 'lg',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    modalRef.componentInstance.title = 'Delete Likelihood';
    modalRef.componentInstance.item = item;
    modalRef.componentInstance.itemType = 'Likelihood';
    modalRef.componentInstance.itemName = item.name;

    modalRef.result.then(
      (result) => {
        if (result === 'confirmed') {
          this.loaderService.show();
          this.likelihoodService
            .deleteLikelihood(item.public_id!)
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
              next: () => {
                this.toast.success('Likelihood deleted successfully.');
                this.loadLikelihoods();
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
   * Handles pagination change.
   */
  public onPageChange(newPage: number): void {
    this.page = newPage;
    this.loadLikelihoods();
  }


  /**
   * Handles page size change.
   */
  public onPageSizeChange(newLimit: number): void {
    this.limit = newLimit;
    this.page = 1;
    this.loadLikelihoods();
  }
}
