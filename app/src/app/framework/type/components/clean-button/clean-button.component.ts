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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, Input, OnChanges, OnDestroy, SimpleChanges } from '@angular/core';

import { ReplaySubject, takeUntil } from 'rxjs';

import { ToastService } from '../../../../layout/toast/toast.service';
import { ObjectService } from '../../../services/object.service';

import { CmdbType } from '../../../models/cmdb-type';
import { NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';
import { CleanupModalComponent } from '../../modals/cleanup-modal/cleanup-modal.component';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-clean-button',
    templateUrl: './clean-button.component.html',
    styleUrls: ['./clean-button.component.scss'],
    standalone: false
})
export class CleanButtonComponent implements OnChanges, OnDestroy {
    // Component un-subscriber
    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();
    // Type of the cleanable objects
    @Input() public type: CmdbType;
    // Object clean status
    public clean: boolean = false;
    // Is the clean status loading
    public loading: boolean = true;
    // Cleanup modal
    private modalRef: NgbModalRef;

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */
    constructor(
        private objectService: ObjectService,
        private modalService: NgbModal,
        private toastService: ToastService
    ) {

    }


    public ngOnChanges(changes: SimpleChanges): void {
        if (changes.type && changes.type.currentValue !== changes.type.previousValue) {
            this.loadObjectCleanStatus();
        }
    }


    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();

        if (this.modalRef) {
            this.modalRef.close();
        }
    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    /**
     * Triggers the clean status api call.
     */
    private loadObjectCleanStatus(): void {
        this.loading = true;

        this.objectService.getObjectCleanStatus(this.type.public_id).pipe(takeUntil(this.subscriber))
        .subscribe((clean: boolean) => {
            this.clean = clean;
            this.loading = false;
        });
    }


    /**
     * Open the clean up modal and handles the close result.
     */
    public openModal(): void {
        this.modalRef = this.modalService.open(CleanupModalComponent);
        this.modalRef.componentInstance.type = this.type;

        this.modalRef.result.then((result) => {
            if (result === 'Clean') {
                this.toastService.success(`Objects of ${ this.type.label } were cleaned up!`);
                this.loadObjectCleanStatus();
                //TODO : reload is done for now but should be replaced 
                // apparantely a delay of 1500ms between this.objectService.cleanObjects and 
                //  this.objectService.getObjectCleanStatus gets the updated data
                window.location.reload();
            }
        });
    }
}
