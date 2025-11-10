import { Component, EventEmitter, Input, OnInit, Output, TemplateRef, ViewChild } from '@angular/core';
import { finalize } from 'rxjs/operators';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { CoreDeleteConfirmationModalComponent } from 'src/app/core/components/dialog/delete-dialog/core-delete-confirmation-modal.component';
import { Impact } from '../../../models/impact.model';
import { ImpactService } from '../../../services/impact.service';
import { IsmsConfig } from '../../../models/isms-config.model';
import { ImpactModalComponent } from './modal/impact-modal.component';
import { Sort, SortDirection } from 'src/app/layout/table/table.types';

@Component({
    selector: 'app-isms-impact',
    templateUrl: './impact.component.html',
    styleUrls: ['./impact.component.scss'],
    standalone: false
})
export class ImpactComponent implements OnInit {
  @ViewChild('actionsTemplate', { static: true }) actionsTemplate: TemplateRef<any>;
  @Input() config: IsmsConfig;
  @Output() impactCountChange = new EventEmitter<number>();


  public impacts: Impact[] = [];
  public totalImpacts = 0;
  public page = 1;
  public limit = 10;
  public loading = false;
  public columns: Array<any>;
  public sort: Sort = { name: 'calculation_basis', order: SortDirection.DESCENDING } as Sort;
  public defaultCalculationBasis: number = -Infinity;

  public isLoading$ = this.loaderService.isLoading$;

  
  constructor(
    private impactService: ImpactService,
    private toast: ToastService,
    private modalService: NgbModal,
    private loaderService: LoaderService
  ) { }


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
        style: { width: '130px'},
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
        style: { width: 'auto'},
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

    this.loadImpacts();
  }


  /**
   * Loads impacts from the backend with pagination and sorting.
   */
  private loadImpacts(): void {
    this.loading = true;
    this.loaderService.show();

    this.impactService
      .getImpacts({
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
          this.impacts = data.results;
          this.totalImpacts = data.total;
          this.impactCountChange.emit(this.impacts.length);
        },
        error: (err) => {
          this.impacts = [];
          this.totalImpacts = 0;
          this.impactCountChange.emit(0);
          this.toast.error(err?.error?.message);
        }
      });
  }


  /**
   * Opens add impact modal.
   */
  public addImpact(): void {
    const maxBasis = Math.max(...this.impacts.map(o => Number(o.calculation_basis)));

    // Set defaultCalculationBasis to 1 if maxBasis is -Infinity, otherwise increment maxBasis
    if (maxBasis === -Infinity) {
      this.defaultCalculationBasis = 1;
    } else if (Number.isInteger(maxBasis)) {
      this.defaultCalculationBasis = maxBasis + 1;
    } else {
      // Don't assign defaultCalculationBasis if it's a decimal
      this.defaultCalculationBasis = undefined;
    }   
    const modalRef = this.modalService.open(ImpactModalComponent, { size: 'lg' });
    modalRef.componentInstance.existingCalculationBases = this.impacts.map(i => i.calculation_basis);
    modalRef.componentInstance.defaultCalculationBasis = this.defaultCalculationBasis;

    // No input => add mode
    modalRef.result.then(
      (result) => {
        if (result === 'saved') {
          this.loadImpacts();
        }
      },
      () => { }
    );
  }


  /**
   * Opens edit impact modal with pre-filled data.
   */
  public editImpact(item: Impact): void {
    const modalRef = this.modalService.open(ImpactModalComponent, { size: 'lg' });
    modalRef.componentInstance.impact = { ...item };
    modalRef.result.then(
      (result) => {
        if (result === 'saved') {
          this.loadImpacts();
        }
      },
      () => { }
    );
  }


  /**
   * Opens delete confirmation modal and deletes the impact on confirm.
   */
  public deleteImpact(item: Impact): void {
    const modalRef = this.modalService.open(CoreDeleteConfirmationModalComponent, { size: 'lg' });
    modalRef.componentInstance.title = 'Delete Impact';
    modalRef.componentInstance.item = item;
    modalRef.componentInstance.itemType = 'Impact';
    modalRef.componentInstance.itemName = item.name;

    modalRef.result.then(
      (result) => {
        if (result === 'confirmed') {
          this.loaderService.show();
          this.impactService
            .deleteImpact(item.public_id!)
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
              next: () => {
                this.toast.success('Impact deleted successfully.');
                this.loadImpacts();
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
    this.loadImpacts();
  }


  /**
   * Handles page size change.
   */
  public onPageSizeChange(newLimit: number): void {
    this.limit = newLimit;
    this.page = 1;
    this.loadImpacts();
  }
}
