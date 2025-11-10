/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { Component, Input, Output, EventEmitter } from '@angular/core';
import { LogService } from '../../../framework/services/log.service';
import { CmdbLog } from '../../../framework/models/cmdb-log';
import { NgbActiveModal, NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { ToastService } from '../../../layout/toast/toast.service';
import { Observable, forkJoin, ReplaySubject } from 'rxjs';
import { finalize, takeUntil } from 'rxjs/operators';
import { LoaderService } from 'src/app/core/services/loader.service';

@Component({
    selector: 'cmdb-modal-content',
    template: `
      <div class="modal-header">
          <h4 class="modal-title" id="modal-basic-title">Delete Log</h4>
          <button
            type="button"
            class="btn-close btn-close-white"
            aria-label="Close"
            (click)="handleModalDismiss()">
            </button>
      </div>
      <div class="modal-body">
         Do you want to delete the log with the ID <b>{{publicID}}</b>?
      </div>
      <div class="modal-footer">
          <button type="button" class="btn btn-warning" (click)="handleModalDismiss()">Close</button>
          <button type="button" class="btn btn-danger" (click)="activeModal.close(this.publicID)">Delete</button>
      </div>
  `,
    standalone: false
})
export class DeleteModalComponent {
    @Input() publicID: number;
    @Output() isDismissClicked = new EventEmitter<boolean>();

    constructor(public activeModal: NgbActiveModal) {
    }

    handleModalDismiss() {
        this.activeModal.dismiss('Cross click')
        this.isDismissClicked.emit(true)
    }
}


@Component({
    selector: 'cmdb-log-object-settings',
    templateUrl: './log-object-settings.component.html',
    styleUrls: ['./log-object-settings.component.scss'],
    standalone: false
})
export class LogObjectSettingsComponent {

    public activeLogList: CmdbLog[];
    public reloadActiveLogs: boolean = false;
    public deActiveLogList: CmdbLog[];
    public reloadDeActiveLogs: boolean = false;
    public deActiveLength: number = 0;
    public deleteLogList: CmdbLog[];
    public reloadDeleteLogs: boolean = false;
    public deleteLogLength: number = 0;
    public cleanupInProgress: boolean = false;
    public cleanupProgress: number = 0;
    isDismissClicked: boolean = false;

    showExistingObjectsLogs: boolean = true;
    showDeletedObjectsLogs: boolean = false;
    showDeleteLogs: boolean = false;
    public isLoading$ = this.loaderService.isLoading$;

    /**
     * Component un-subscriber.
     */
    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    constructor(
        private logService: LogService, 
        private modalService: NgbModal, 
        private toastService: ToastService,
        private loaderService: LoaderService) {
    }


    /**
   * Handles the click event on nav items.
   * Sets the corresponding boolean flags to control which nav item to display.
   * @param navItem The index of the clicked nav item.
   */
    handleClick(navItem: number) {
        this.showExistingObjectsLogs = navItem === 1;
        this.showDeletedObjectsLogs = navItem === 2;
        this.showDeleteLogs = navItem === 3;
    }


    public deleteLog(publicID: number, reloadList: string) {
        const deleteModalRef = this.modalService.open(DeleteModalComponent);
        deleteModalRef.componentInstance.publicID = publicID;
        deleteModalRef.componentInstance.isDismissClicked.subscribe((dismissed: boolean) => {
            this.isDismissClicked = dismissed
        });
        deleteModalRef.result.then(result => {
            this.loaderService.show();
            this.logService.deleteLog(result).pipe(takeUntil(this.subscriber), finalize(() => this.loaderService.hide())).subscribe(() => {
                this.toastService.success('Log was deleted!');
            }, (error) => {
                        this.toastService.error(error?.error?.message)  },
                () => {
                    switch (reloadList) {
                        case 'active':
                            this.reloadActiveLogs = false;
                            setTimeout(() => this.reloadActiveLogs = true, 0);
                            break;
                        case 'deactive':
                            this.reloadDeActiveLogs = false;
                            setTimeout(() => this.reloadDeActiveLogs = true, 0);
                            break;
                        case 'delete':
                            this.reloadDeleteLogs = false;
                            setTimeout(() => this.reloadDeleteLogs = true, 0);
                            break;
                    }
                }
            );
        },
            (error) => {
                if (!this.isDismissClicked && error !== 'Cross click') {
                    console.error(error);
                }
            });
    }


    public cleanup(publicIDs: number[], reloadList: string) {
        this.cleanupInProgress = true;
        const entriesLength = publicIDs.length;
        const step = 100 / entriesLength;
        const deleteObserves: Observable<any>[] = [];
        for (const logID of publicIDs) {
            deleteObserves.push(this.logService.deleteLog(logID));
            this.cleanupProgress += step;
        }
        forkJoin(deleteObserves)
            .subscribe({
                next: () => {
                    this.cleanupInProgress = false;
                },
                error: (error) => console.error(error),
                complete: () => {
                    switch (reloadList) {
                        case 'active':
                            this.reloadActiveLogs = true;
                            break;
                        case 'deactive':
                            this.reloadDeActiveLogs = true;
                            break;
                        case 'delete':
                            this.reloadDeleteLogs = true;
                            break;
                    }
                }
            });

    }
}
