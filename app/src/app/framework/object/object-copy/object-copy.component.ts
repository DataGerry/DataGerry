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
import { Component, HostListener, OnDestroy, OnInit } from '@angular/core';
import { UntypedFormGroup } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { ObjectService } from '../../services/object.service';
import { UserService } from '../../../management/services/user.service';
import { TypeService } from '../../services/type.service';
import { SidebarService } from '../../../layout/services/sidebar.service';
import { ToastService } from '../../../layout/toast/toast.service';
import { LocationService } from '../../services/location.service';

import { CmdbMode } from '../../modes.enum';
import { CmdbObject } from '../../models/cmdb-object';
import { RenderResult } from '../../models/cmdb-render';
import { CmdbType } from '../../models/cmdb-type';
import { APIUpdateMultiResponse } from '../../../services/models/api-response';
import { LoaderService } from 'src/app/core/services/loader.service';
import { finalize } from 'rxjs';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-object-copy',
    templateUrl: './object-copy.component.html',
    styleUrls: ['./object-copy.component.scss'],
    standalone: false
})
export class ObjectCopyComponent implements OnInit, OnDestroy {

    public mode: CmdbMode = CmdbMode.Edit;
    private objectID: number;
    public typeInstance: CmdbType;
    public renderResult: RenderResult;
    public renderForm: UntypedFormGroup;

    private originalLocationData: RenderResult;
    private newLocationParentID: number = 0;
    public isLoading$ = this.loaderService.isLoading$;


    /* ------------------------------------------------------------------------------------------------------------------ */
    /*                                                     LIFE CYCLE                                                     */
    /* ------------------------------------------------------------------------------------------------------------------ */

    constructor(private objectService: ObjectService,
        private typeService: TypeService,
        private route: ActivatedRoute,
        private router: Router,
        private userService: UserService,
        private sidebarService: SidebarService,
        private toastService: ToastService,
        private locationService: LocationService,
        private loaderService: LoaderService,) {

        this.route.params.subscribe((params) => {
            this.objectID = params.publicID;
        });

        this.renderForm = new UntypedFormGroup({});
    }


    public ngOnInit(): void {
        this.loaderService.show();
        this.objectService.getObject(this.objectID).pipe(finalize(() => this.loaderService.hide())).subscribe((rr: RenderResult) => {
            this.renderResult = rr;

            for (let field of this.renderResult.fields) {
                if (field['name'] == 'dg_location' && field['value'] > 0) {
                    this.getOriginalObjectLocation();
                }
            }

        },
            error => {
                this.toastService.error(error?.error?.message)
            },
            () => {
                this.typeService.getType(this.renderResult.type_information.type_id).subscribe((value: CmdbType) => {
                    this.typeInstance = value;
                });
            });
    }


    public ngOnDestroy(): void {
        this.locationService.locationTreeName = "";
    }
    /* ------------------------------------------------------------------------------------------------------------------ */
    /*                                                      API CALLS                                                     */
    /* ------------------------------------------------------------------------------------------------------------------ */

    public copyObject(): void {
        this.renderForm.markAllAsTouched();

        if (this.renderForm.valid) {
            this.loaderService.show();
            const newObjectInstance = new CmdbObject();
            newObjectInstance.type_id = this.renderResult.type_information.type_id;
            newObjectInstance.active = this.renderResult.type_information.active;
            newObjectInstance.version = '1.0.0';
            newObjectInstance.author_id = this.userService.getCurrentUser().public_id;
            newObjectInstance.fields = [];

            Object.keys(this.renderForm.controls).forEach(field => {
                if (field == 'dg_location' && this.renderForm.get(field).value > 0) {
                    this.newLocationParentID = this.renderForm.get(field).value;
                }

                if (field.startsWith("dg-mds-")) {
                    newObjectInstance.multi_data_sections.push(this.renderForm.get(field).value)
                } else {
                    newObjectInstance.fields.push({
                        name: field,
                        value: this.renderForm.get(field).value
                    });
                }
            });

            let ack = null;
            this.objectService.postObject(newObjectInstance).pipe(finalize(() => this.loaderService.hide()))
                .subscribe({
                    next: (newObjectID) => {
                        ack = newObjectID;

                        if (this.newLocationParentID > 0) {
                            this.createNewObjectLocation(ack);
                        }
                    },
                    error: (e) => {
                        this.toastService.error(e?.error?.message);
                    },
                    complete: () => {
                        this.router.navigate(['/framework/object/view/' + ack]);
                        this.sidebarService.updateTypeCounter(this.renderResult.type_information.type_id);
                        this.toastService.success(`Object ${this.objectID} was successfully copied into ${ack}!`);
                    }
                });
        }
    }


    private getOriginalObjectLocation() {
        this.locationService.getLocationForObject(this.renderResult.object_information.object_id)
            .subscribe((response: RenderResult) => {
                this.originalLocationData = response;

                // Set the inital name for the location for copying and creating a new one
                this.locationService.locationTreeName = this.originalLocationData['name'];
            });
    }


    private createNewObjectLocation(newObjectID: number) {
        let params = {
            "object_id": newObjectID,
            "parent": this.newLocationParentID,
            "name": this.locationService.locationTreeName,
            "type_id": this.typeInstance.public_id
        }

        this.locationService.postLocation(params)
            .subscribe({
                next: (res: APIUpdateMultiResponse) => {
                    this.locationService.locationTreeName = "";
                },
                error: (error) => {
                    this.toastService.error(error?.error?.message);
                }
            }
            );
    }

    /* ------------------------------------------------- HELPER SECTION ------------------------------------------------- */

    @HostListener('window:scroll')
    onWindowScroll() {
        const dialog = document.getElementById('object-form-action');

        if (document.body.scrollTop > 20 || document.documentElement.scrollTop > 20) {
            dialog.style.visibility = 'visible';
        } else {
            dialog.style.visibility = 'hidden';
        }
    }
}
