import { Component, Input, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { finalize } from 'rxjs/operators';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ProtectionGoal } from 'src/app/toolbox/isms/models/protection-goal.model';
import { ProtectionGoalService } from 'src/app/toolbox/isms/services/protection-goal.service'; import { IsmsConfig } from 'src/app/toolbox/isms/models/isms-config.model';

import { CoreDeleteConfirmationModalComponent } from 'src/app/core/components/dialog/delete-dialog/core-delete-confirmation-modal.component';
import { ProtectionGoalModalComponent } from './modal/protection-goal-modal.component';

@Component({
    selector: 'app-isms-protection-goals',
    templateUrl: './protection-goals.component.html',
    styleUrls: ['./protection-goals.component.scss'],
    standalone: false
})
export class ProtectionGoalsComponent implements OnInit {
  @ViewChild('actionsTemplate', { static: true }) actionsTemplate: TemplateRef<any>;
  @Input() config: IsmsConfig;

  public protectionGoals: ProtectionGoal[] = [];
  public totalProtectionGoals = 0;
  public page = 1;
  public limit = 10;
  public loading = false;
  public columns: Array<any> = [];

  constructor(
    private protectionGoalService: ProtectionGoalService,
    private toast: ToastService,
    private modalService: NgbModal,
    private loaderService: LoaderService
  ) { }


  ngOnInit(): void {
    this.columns = [
      // {
      //   display: 'Public ID',
      //   name: 'public_id',
      //   data: 'public_id',
      //   searchable: true,
      //   sortable: false,
      //   style: { width: '120px', 'text-align': 'center' }
      // },
      {
        display: 'Name',
        name: 'name',
        data: 'name',
        searchable: true,
        sortable: false,
        cssClasses: ['text-center'],
      },
      {
        display: 'Actions',
        name: 'actions',
        template: this.actionsTemplate,
        sortable: false,
        style: { width: '140px', 'text-align': 'center' }
      }
    ];
    this.loadProtectionGoals();
  }


  /**
   * Loads protection goals from the backend.
   */
  private loadProtectionGoals(): void {
    this.loading = true;
    this.loaderService.show();

    this.protectionGoalService.getProtectionGoals({
      filter: '',
      limit: this.limit,
      page: this.page,
      sort: 'public_id',
      order: 1
    })
      .pipe(finalize(() => {
        this.loaderService.hide();
        this.loading = false;
      }))
      .subscribe({
        next: (data) => {
          this.protectionGoals = data.results;
          this.totalProtectionGoals = data.total;
        },
        error: (err) => {
          this.protectionGoals = [];
          this.totalProtectionGoals = 0;
          this.toast.error(err?.error?.message);
        }
      });
  }


  /**
   * Opens modal to add a new protection goal.
   */
  public addProtectionGoal(): void {
    const modalRef = this.modalService.open(ProtectionGoalModalComponent, { size: 'lg' });
    modalRef.componentInstance.protectionGoals = this.protectionGoals;
    modalRef.result.then(
      (result) => {
        if (result === 'saved') {
          this.loadProtectionGoals();
        }
      },
      () => { }
    );
  }


  /**
   * Opens modal to edit selected protection goal.
   */
  public editProtectionGoal(item: ProtectionGoal): void {
    const modalRef = this.modalService.open(ProtectionGoalModalComponent, { size: 'lg' });
    modalRef.componentInstance.protectionGoal = { ...item };
    modalRef.result.then(
      (result) => {
        if (result === 'saved') {
          this.loadProtectionGoals();
        }
      },
      () => { }
    );
  }


  /**
   * Deletes a protection goal after confirmation.
   * Prevents deletion of default goals (ID 1, 2, 3).
   */
  public deleteProtectionGoal(item: ProtectionGoal): void {
    // Prevent deletion of default goals with public_id 1, 2, or 3.
    if (item.public_id === 1 || item.public_id === 2 || item.public_id === 3) {
      this.toast.warning('Default protection goals cannot be deleted.');
      return;
    }
    const modalRef = this.modalService.open(CoreDeleteConfirmationModalComponent, { size: 'lg' });
    modalRef.componentInstance.title = 'Delete Protection Goal';
    modalRef.componentInstance.item = item;
    modalRef.componentInstance.itemType = 'Protection Goal';
    modalRef.componentInstance.itemName = item.name;

    modalRef.result.then(
      (result) => {
        if (result === 'confirmed') {
          this.loaderService.show();
          this.protectionGoalService.deleteProtectionGoal(item.public_id!)
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
              next: () => {
                this.toast.success('Protection Goal deleted successfully.');
                this.loadProtectionGoals();
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
   * Handles pagination page change.
   */
  public onPageChange(newPage: number): void {
    this.page = newPage;
    this.loadProtectionGoals();
  }


  /**
   * Checks if a protection goal is a default (cannot be deleted).
   */
  public isDefaultProtectionGoal(item: ProtectionGoal): boolean {
    return item.predefined === true;
  }

}
