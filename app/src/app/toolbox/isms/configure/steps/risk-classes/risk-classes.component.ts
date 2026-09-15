import {
  Component,
  inject,
  EventEmitter,
  Input,
  OnInit,
  Output,
  TemplateRef,
  ViewChild,
} from '@angular/core';
import { debounceTime, distinctUntilChanged, finalize, switchMap } from 'rxjs/operators';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { LoaderService } from 'src/app/core/services/loader.service';

import { RiskClass } from '../../../models/risk-class.model';
import { RiskClassService } from '../../../services/risk-class.service';
import { IsmsConfig } from '../../../models/isms-config.model';
import { CoreDeleteConfirmationModalComponent } from 'src/app/core/components/dialog/delete-dialog/core-delete-confirmation-modal.component';
import { RiskClassModalComponent } from './modal/add-risk-class-modal.component';
import { Subject } from 'rxjs';
import { Warning } from 'src/app/core/models/warning.model';
import { getTextColorBasedOnBackground } from 'src/app/core/utils/color-utils';

@Component({
    selector: 'app-isms-risk-classes',
    templateUrl: './risk-classes.component.html',
    styleUrls: ['./risk-classes.component.scss'],
    standalone: false
})
export class RiskClassesComponent implements OnInit {
  private readonly riskClassService = inject(RiskClassService);
  private readonly toast = inject(ToastService);
  private readonly modalService = inject(NgbModal);
  private readonly loaderService = inject(LoaderService);

  // Table column templates
  @ViewChild('actionsTemplate', { static: true }) actionsTemplate: TemplateRef<any>;
  @ViewChild('colorTemplate', { static: true }) colorTemplate: TemplateRef<any>;
  //  pass a config from the wizard container
  @Input() config: IsmsConfig;
  @Output() riskClassesCountChange = new EventEmitter<number>();

  private orderChangeSubject = new Subject<RiskClass[]>();
  public riskClasses: RiskClass[] = [];
  public totalRiskClasses: number = 0;
  public warnings: Warning[] = [];
  public page = 1;
  public limit = 10;
  public loading = false;
  public columns: Array<any>;
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
        display: 'Color',
        name: 'color',
        data: 'color',
        template: this.colorTemplate,
        sortable: false,
        style: { width: '120px', 'text-align': 'center' }
      },
      {
        display: 'Name',
        name: 'label',
        data: 'name',
        sortable: false,
        cssClasses: ['text-center'],

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
        style: { width: '100px', 'text-align': 'center' }
      }
    ];

    this.loadRiskClasses();
    this.setupDebouncedOrderChange();

  }


  /**
   * Loads Risk Classes from the server with pagination.
   */
  private loadRiskClasses(): void {
    this.loading = true;
    this.loaderService.show();

    this.riskClassService
      .getRiskClasses({
        filter: '',
        limit: this.limit,
        page: this.page,
        sort: 'sort',
        order: 1
      })
      .pipe(
        finalize(() => {
          this.loaderService.hide();
          this.loading = false;
        })
      )
      .subscribe({
        next: (data) => {
          // this.riskClasses = data.results;
          this.riskClasses = data.results.map((riskClass) => ({
            ...riskClass,
            textColor: getTextColorBasedOnBackground(riskClass.color)
          }));
          this.totalRiskClasses = data.total;

          this.config.riskClasses = this.riskClasses;
          this.riskClassesCountChange.emit(this.riskClasses.length);
          this.updateWarnings();
        },
        error: (err) => {
          this.riskClasses = [];
          this.riskClassesCountChange.emit(0);
          this.toast.error(err?.error?.message);
        }
      });
  }

  /**
   * Opens modal to ADD a new Risk Class.
   */
  public addRiskClass(): void {

    const modalRef = this.modalService.open(RiskClassModalComponent, {
      size: 'lg',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    modalRef.componentInstance.sort = this.totalRiskClasses
    // No input => the modal knows it's creating a new record
    modalRef.result.then(
      (result) => {
        if (result === 'saved') {
          this.loadRiskClasses();
        }
      },
      () => {
        // Modal dismissed
      }
    );
  }


  /**
   * Opens modal to EDIT an existing Risk Class.
   */
  public editRiskClass(item: RiskClass): void {
    const modalRef = this.modalService.open(RiskClassModalComponent, {
      size: 'lg',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    // Pass existing item => the modal is in edit mode
    modalRef.componentInstance.riskClass = { ...item };
    modalRef.result.then(
      (result) => {
        if (result === 'saved') {
          this.loadRiskClasses();
        }
      },
      () => {
        // Modal dismissed
      }
    );
  }


  /**
   * Deletes a Risk Class after user confirms in CoreDeleteConfirmationModalComponent.
   */
  public onDeleteRiskClass(item: RiskClass): void {
    const modalRef = this.modalService.open(CoreDeleteConfirmationModalComponent, {
      size: 'lg',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    modalRef.componentInstance.title = 'Delete Risk Class';
    modalRef.componentInstance.item = item;
    modalRef.componentInstance.itemType = 'Risk Class';
    modalRef.componentInstance.itemName = item.name;

    modalRef.result.then(
      (result) => {
        if (result === 'confirmed') {
          this.loaderService.show();
          this.riskClassService
            .deleteRiskClass(item?.public_id!)
            .pipe(finalize(() => {
              this.loaderService.hide();
            }))
            .subscribe({
              next: () => {
                this.toast.success('Risk Class deleted successfully.');
                this.loadRiskClasses();
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
   * Handle table pagination page change.
   */
  public onPageChange(newPage: number): void {
    this.page = newPage;
    this.loadRiskClasses();
  }


  /**
   * Handle table page size (limit) change.
   */
  public onPageSizeChange(newLimit: number): void {
    this.limit = newLimit;
    this.page = 1;
    this.loadRiskClasses();
  }


  /**
    * handle row reordering
    */
  public onOrderChange(newItems: RiskClass[]): void {
    this.riskClasses = newItems.map((item, index) => ({
      ...item,
      sort: index
    }));

    this.orderChangeSubject.next(this.riskClasses);
  }



  /**
   *  Sets up the stream that will handle order-change events and
   *  make the API call only after a short pause (debounce).
   */
  private setupDebouncedOrderChange(): void {
    this.orderChangeSubject
      .pipe(
        debounceTime(300),
        // Only trigger when the emitted array actually changes
        distinctUntilChanged(
          (prev, curr) => JSON.stringify(prev) === JSON.stringify(curr)
        ),
        // Switch to the actual API call
        switchMap((updatedItems) => {
          this.loaderService.show();
          return this.riskClassService.updateRiskClassOrder(updatedItems)
            .pipe(
              finalize(() => this.loaderService.hide())
            );
        })
      )
      .subscribe({
        next: (res) => {
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }

  /**
   * Updates the warnings based on the current risk classes.
   * @returns void
   */
  private updateWarnings(): void {
    this.warnings = [];

    if (this.totalRiskClasses < 3) {
      this.warnings.push({
        iconClass: 'fas fa-exclamation-triangle',
        title: 'Structural Advisory:',
        message: 'At least three risk classes are required.'
      });
    }

    if (this.totalRiskClasses > 0) {
      this.warnings.push({
        iconClass: 'fas fa-sort',
        title: 'Structural Advisory:',
        message: 'Please sort your risk classes from High to Low.'
      });
    }
  }

}
