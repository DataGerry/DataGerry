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
import { Component, EventEmitter, HostListener, OnDestroy, OnInit, Output, ViewChild } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { BehaviorSubject, Observable, ReplaySubject, takeUntil } from 'rxjs';

import { TypeService } from '../../services/type.service';
import { UserService } from '../../../management/services/user.service';
import { ObjectService } from '../../services/object.service';
import { SidebarService } from '../../../layout/services/sidebar.service';
import { ToastService } from '../../../layout/toast/toast.service';
import { LocationService } from '../../services/location.service';

import { CmdbType } from '../../models/cmdb-type';
import { CmdbMode } from '../../modes.enum';
import { RenderComponent } from '../../render/render.component';
import { CmdbObject } from '../../models/cmdb-object';
import { AccessControlPermission } from 'src/app/modules/acl/acl.types';
import { finalize } from 'rxjs/operators';
import { LoaderService } from 'src/app/core/services/loader.service';

/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-object-add',
    templateUrl: './object-add.component.html',
    styleUrls: ['./object-add.component.scss']
})
export class ObjectAddComponent implements OnInit, OnDestroy {
    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    public typeList: CmdbType[] = [];
    public typeIDForm: UntypedFormGroup;
    private typeIDSubject: BehaviorSubject<number>;
    public typeID: Observable<number>;
    public typeInstance: CmdbType;
    public mode: CmdbMode = CmdbMode.Create;
    public objectInstance: CmdbObject;
    public renderForm: UntypedFormGroup;
    public fieldsGroups: UntypedFormGroup;
    public isLoading$ = this.loaderService.isLoading$;

    @Output() parentSubmit = new EventEmitter<any>();
    @ViewChild(RenderComponent, { static: false }) render: RenderComponent;

    private parentID: number;
    public isSaving: boolean = false;

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(private router: Router,
        private typeService: TypeService,
        private objectService: ObjectService,
        private userService: UserService,
        private route: ActivatedRoute,
        private sidebarService: SidebarService,
        private locationService: LocationService,
        private toastService: ToastService,
        private loaderService: LoaderService,
    ) {

        this.objectInstance = new CmdbObject();
        this.typeIDSubject = new BehaviorSubject<number>(null);

        this.route.params.subscribe((params) => {
            if (params.publicID !== undefined) {
                this.typeIDSubject.next(+params.publicID);
            }
        });

        this.typeID = this.typeIDSubject.asObservable();

        this.typeID.pipe(takeUntil(this.subscriber)).subscribe(selectedTypeID => {
            if (selectedTypeID !== null) {
                this.typeService.getType(selectedTypeID).subscribe((typeInstance: CmdbType) => {
                    this.typeInstance = typeInstance;
                });
            }
        });

        this.fieldsGroups = new UntypedFormGroup({});
        this.renderForm = new UntypedFormGroup({
            active: new UntypedFormControl(true)
        });
    }


    public ngOnInit(): void {
        this.loaderService.show();
        this.typeService.getTypeList(AccessControlPermission.CREATE).pipe(takeUntil(this.subscriber),
             finalize(() => this.loaderService.hide()))
            .subscribe({
                next: (typeList: CmdbType[]) => {
                    this.typeList = typeList;
                },
                error: (error) => {
                    this.toastService.error(error);
                }
            });

        this.typeIDForm = new UntypedFormGroup({
            typeID: new UntypedFormControl(null, Validators.required)
        });
    }


    public ngOnDestroy(): void {
        this.typeIDSubject?.unsubscribe();
        this.subscriber?.next();
        this.subscriber?.complete();
    }

    /* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    public get formTypeID() {
        return this.typeIDForm.get('typeID').value;
    }


    public useTypeID() {
        this.typeIDSubject.next(this.formTypeID);
    }


    public get currentTypeID() {
        return this.typeIDSubject.value;
    }


    public saveObject() {
        this.renderForm.markAllAsTouched();
        if (this.renderForm.valid) {

            if (this.isSaving) {
                return;
            }
            this.loaderService.show();
            this.isSaving = true;

            this.objectInstance.type_id = this.currentTypeID;
            this.objectInstance.version = '1.0.0';
            this.objectInstance.author_id = this.userService.getCurrentUser().public_id;
            this.objectInstance.ci_explorer_tooltip = null;

            this.objectInstance.fields = [];
            this.render.renderForm.removeControl('active');

            Object.keys(this.render.renderForm.controls).forEach(field => {
                let val = this.renderForm.value[field];

                if (field == 'dg_location') {
                    this.parentID = val;
                }

                if (val === undefined || val == null) {
                    val = '';
                }

                //set the multi data section
                if (field.startsWith('dg-mds-')) {
                    this.objectInstance.multi_data_sections.push(val);
                } else {
                    //just set the field
                    this.objectInstance.fields.push({
                        name: field,
                        value: val
                    });
                }

            });

            let newID = null;
            this.objectService.postObject(this.objectInstance).pipe(takeUntil(this.subscriber),
            finalize(() => {
                this.loaderService.hide();
                this.isSaving = false;
            }))
                .subscribe({
                    next: newObjectID => {
                        newID = newObjectID;
                        this.createLocation(newID);
                    },
                    error: (e) => {
                        this.toastService.error(e?.error?.message)
                    },
                    complete: () => {
                        this.router.navigate(['/framework/object/view/' + newID]);
                        this.sidebarService.updateTypeCounter(this.typeInstance.public_id);
                        this.toastService.success(`Object ${newID} was created succesfully!`);
                    }
                });
        }
    }


    private createLocation(newObjectID: number) {
        let params = {
            "object_id": newObjectID,
            "parent": this.parentID,
            "name": this.locationService.locationTreeName,
            "type_id": this.objectInstance.type_id
        }

        if (this.parentID) {
            this.locationService.postLocation(params).pipe(
                finalize(() => this.loaderService.hide())
            )
                .subscribe({
                    next: () => {
                        this.locationService.locationTreeName = "";
                    },
                    error: error => {
                        this.toastService.error(error);
                    }
                });
        }
    }


    @HostListener('window:scroll')
    onWindowScroll() {
        const dialog = document.getElementById('object-form-action');

        if (dialog) {
            if ((document.body.scrollTop > 10 || document.documentElement.scrollTop > 10)) {
                dialog.style.visibility = 'visible';
            } else {
                dialog.style.visibility = 'hidden';
            }
        }
    }
}