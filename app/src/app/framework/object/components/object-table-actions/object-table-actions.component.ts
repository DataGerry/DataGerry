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
import { Component, EventEmitter, Input, OnDestroy, Output } from '@angular/core';
import { NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';

import { ReplaySubject, takeUntil } from 'rxjs';

import { LocationService } from 'src/app/framework/services/location.service';
import { ObjectService } from 'src/app/framework/services/object.service';

import { ObjectPreviewModalComponent } from '../../modals/object-preview-modal/object-preview-modal.component';
import { ObjectDeleteModalComponent } from '../../modals/object-delete-modal/object-delete-modal.component';
import { RenderResult } from '../../../models/cmdb-render';
import { AccessControlList } from 'src/app/modules/acl/acl.types';
import { ToastService } from 'src/app/layout/toast/toast.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-object-table-actions',
    templateUrl: './object-table-actions.component.html',
    styleUrls: ['./object-table-actions.component.scss'],
    standalone: false
})
export class ObjectTableActionsComponent implements OnDestroy {

    // Component wide un-subscriber
    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    // Public id of the object
    @Input() public publicID: number;

    // Rendered object
    @Input() public result: RenderResult;

    @Input() public acl: AccessControlList;

    // Emitter when element was deleted.
    @Output() public deleteEmitter: EventEmitter<number> = new EventEmitter<number>();

    // Emitters when element was deleted with required location handling
    @Output() public deleteObjectsEmitter: EventEmitter<number> = new EventEmitter<number>();
    @Output() public deleteLocationsEmitter: EventEmitter<number> = new EventEmitter<number>();

    private modalRef: NgbModalRef;

    private locationSubscription: ReplaySubject<void> = new ReplaySubject<void>();

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    constructor(
        private locationService: LocationService, 
        private objectService: ObjectService, 
        private modalService: NgbModal,
        private toastService: ToastService,
    ) {

    }


    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();

        if (this.modalRef) {
            this.modalRef.close();
        }
    }

/* -------------------------------------------------- MODAL SECTION ------------------------------------------------- */

    /**
     * Open the preview modal
     */
    public openPreviewModal(): void {
        this.modalRef = this.modalService.open(ObjectPreviewModalComponent, { size: 'lg' });
        this.modalRef.componentInstance.renderResult = this.result;
    }


    public handleDelete(publicID: number){
        // first check if the object has a location which is parent to child locations
        this.locationService.getChildren(publicID).pipe(takeUntil(this.locationSubscription))
        .subscribe({
            next: (children: RenderResult[]) => {
                if(children && children.length > 0){
                    this.deleteWithLocations(publicID);
                } else {
                    this.deleteObject(publicID);
                }
            },
            error: (error) => {
                this.toastService.error(error?.error?.message)
            }
        });
    }


    public deleteObject(publicID: number) {
        this.modalRef = this.modalService.open(ObjectDeleteModalComponent, { size: 'lg' });
        this.modalRef.componentInstance.publicID = this.result.object_information.object_id;

        this.modalRef.result.then((response: any) => {
            if(response > 0){
              this.deleteEmitter.emit(response);
            }
        });
    }


    private deleteWithLocations(publicID: number){
        this.modalRef = this.objectService.openLocationModalComponent();

        this.modalRef.result.then((result) => {
            //delete all child objects with their locations
            if(result == 'objects'){
              this.deleteObjectsEmitter.emit(publicID);
            }

            //delete only locations of children
            if(result == 'locations'){
              this.deleteLocationsEmitter.emit(publicID);
            }
        });
    }
}