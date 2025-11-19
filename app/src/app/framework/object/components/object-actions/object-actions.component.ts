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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import {Component, Input, OnDestroy} from '@angular/core';
import { Router } from '@angular/router';

import { finalize, ReplaySubject, takeUntil } from 'rxjs';

import { NgbModalRef } from '@ng-bootstrap/ng-bootstrap';

import { ObjectService } from '../../../services/object.service';
import { LocationService } from 'src/app/framework/services/location.service';
import { SidebarService } from 'src/app/layout/services/sidebar.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { RenderResult } from '../../../models/cmdb-render';
import { AccessControlList } from 'src/app/modules/acl/acl.types';
import { LoaderService } from 'src/app/core/services/loader.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-object-actions',
    templateUrl: './object-actions.component.html',
    styleUrls: ['./object-actions.component.scss'],
    standalone: false
})
export class ObjectActionsComponent implements OnDestroy {

    @Input() renderResult: RenderResult;
    @Input() acl: AccessControlList;

    public subscriber: ReplaySubject<void>;
    private locationSubscription: ReplaySubject<void> = new ReplaySubject<void>();
    public isLoading$ = this.loaderService.isLoading$;

    private modalRef: NgbModalRef;

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(private objectService: ObjectService, 
                private locationService: LocationService, 
                private sidebarService: SidebarService, 
                private toastService: ToastService, 
                private router: Router,
                private loaderService: LoaderService,
             ) {

        this.subscriber = new ReplaySubject<void>();
    }


    public ngOnDestroy(): void {
        if (this.modalRef) {
            this.modalRef.close();
        }

        this.subscriber?.unsubscribe();
        this.locationSubscription?.unsubscribe();
    }

/* ------------------------------------------------- MODAL FUNCTIONS ------------------------------------------------ */

    /**
     * Decides if it a normal delete or locations are involved
     * 
     * @param publicID public_id of object which should be deleted
     */
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
            error:  (error) => {
            }
        });
    }


    /**
     * ModalView to delete object with given public_id
     * 
     * @param publicID public_id of object which should be deleted
     */
    public deleteObject(publicID: number) {
        this.modalRef = this.objectService.openModalComponent(
            'Delete Object',
            'Are you sure you want to delete this Object?',
            'Cancel',
            'Delete'
        );

        this.modalRef.result.then((result) => {
            if (result) {
                this.loaderService.show();
                this.objectService.deleteObject(publicID).pipe(takeUntil(this.subscriber), finalize(() => this.loaderService.hide()))
                .subscribe({
                    next: () => {
                        this.toastService.success(`Object ${ this.renderResult.object_information.object_id } was deleted succesfully!`);
                        this.router.navigate(['/framework/object/type/' + this.renderResult.type_information.type_id]);
                        this.sidebarService.updateTypeCounter(this.renderResult.type_information.type_id);
                    },
                    error: (error) => {
                        this.toastService.error(error?.error?.message);
                    }
                });
            }
        });
    }


    /**
     * Opens a modal where the user has to decide to either delete locations with objects or only locations
     * of sub nodes in the location tree
     * @param publicID 
     */
    private deleteWithLocations(publicID: number){
      this.modalRef = this.objectService.openLocationModalComponent();

      this.modalRef.result.then((result) => {
            //delete all child objects with their locations
            if(result == 'objects'){
                this.objectService.deleteObjectWithChildren(publicID).pipe(takeUntil(this.subscriber))
                .subscribe({
                    next: () => {
                        this.toastService.success(`Object ${ this.renderResult.object_information.object_id } and child locations were deleted succesfully!`);
                        this.router.navigate(['/framework/object/type/' + this.renderResult.type_information.type_id]);
                        this.sidebarService.updateTypeCounter(this.renderResult.type_information.type_id);
                    },
                    error: (error) => {
                        this.toastService.error(error?.error?.message);
                    }
                });
            }

            //delete only locations of children
            if(result == 'locations'){
                this.objectService.deleteObjectWithLocations(publicID).pipe(takeUntil(this.subscriber))
                .subscribe({
                    next: () => {
                        this.toastService.success(`Object ${ this.renderResult.object_information.object_id } and child locations were deleted succesfully!`);
                        this.router.navigate(['/framework/object/type/' + this.renderResult.type_information.type_id]);
                        this.sidebarService.updateTypeCounter(this.renderResult.type_information.type_id);
                    },
                    error: (error) => {
                        this.toastService.error(error?.error?.message);
                    }
                });
            }
      });
    }
}