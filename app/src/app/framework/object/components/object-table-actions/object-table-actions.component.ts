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
import { Component, inject, EventEmitter, Input, OnDestroy, Output } from '@angular/core';
import { NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';

import { ReplaySubject, takeUntil } from 'rxjs';

import { LocationService } from 'src/app/framework/services/location.service';
import { ObjectService } from 'src/app/framework/services/object.service';

import { ObjectPreviewModalComponent } from '../../modals/object-preview-modal/object-preview-modal.component';
import { ObjectDeleteModalComponent } from '../../modals/object-delete-modal/object-delete-modal.component';
import { RenderResult } from '../../../models/cmdb-render';
import { AccessControlList } from 'src/app/modules/acl/acl.types';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LicenseFeature } from 'src/app/settings/license-management/models/license.model';
import { PremiumFeatureService } from 'src/app/settings/license-management/premium-feature/premium-feature.service';
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

    private readonly locationService = inject(LocationService);
    private readonly objectService = inject(ObjectService);
    private readonly modalService = inject(NgbModal);
    private readonly toastService = inject(ToastService);
    private readonly premiumFeatureService = inject(PremiumFeatureService);


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
        if (this.isPremiumLocked()) {
            this.premiumFeatureService.promptUpgrade(LicenseFeature.Ipam);
            return;
        }

        this.modalRef = this.modalService.open(ObjectPreviewModalComponent, {
            size: 'xl',
            scrollable: true,
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });
        this.modalRef.componentInstance.renderResult = this.result;
    }


    public handleDelete(publicID: number){
        if (this.isPremiumLocked()) {
            this.premiumFeatureService.promptUpgrade(LicenseFeature.Ipam);
            return;
        }

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
        this.modalRef = this.modalService.open(ObjectDeleteModalComponent, {
            size: 'lg',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });
        this.modalRef.componentInstance.publicID = this.result.object_information.object_id;

        this.modalRef.result.then((response: any) => {
            if(response > 0){
              this.deleteEmitter.emit(response);
            }
        });
    }


    /**
     * A special-type (IPAM) object is locked for preview/delete when IPAM is not part of the edition.
     * View/edit/copy navigate and are blocked by the route guard, so they are not re-checked here.
     */
    private isPremiumLocked(): boolean {
        return !!this.result?.object_information?.special_type
            && !this.premiumFeatureService.isAvailable(LicenseFeature.Ipam);
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