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
import { Component, HostListener, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { Location } from '@angular/common';

import { ObjectService } from '../../services/object.service';
import { ToastService } from '../../../layout/toast/toast.service';
import { TypeService } from '../../services/type.service';
import { SidebarService } from 'src/app/layout/services/sidebar.service';

import { CmdbMode } from '../../modes.enum';
import { CmdbObject, MultiDataSectionEntry, MultiDataSectionFieldValue, ObjectPatchPayload } from '../../models/cmdb-object';
import { RenderResult } from '../../models/cmdb-render';
import { CmdbType } from '../../models/cmdb-type';
import { Column } from 'src/app/layout/table/table.types';
import { LoaderService } from 'src/app/core/services/loader.service';
import { finalize } from 'rxjs';
import { buildObjectPatchPayload } from './object-patch.util';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-object-edit',
    templateUrl: './object-edit.component.html',
    styleUrls: ['./object-edit.component.scss'],
    standalone: false
})
export class ObjectEditComponent implements OnInit {
    public mode: CmdbMode = CmdbMode.Edit;
    public objectInstance: CmdbObject;
    public typeInstance: CmdbType;
    public renderResult: RenderResult;
    public renderForm: UntypedFormGroup;
    public commitForm: UntypedFormGroup;
    private objectID: number;
    public activeState: boolean;

    // Object state as loaded from the backend, used to diff the PATCH payload
    private originalSnapshot: CmdbObject;

    public selectedLocation: number = -1;
    public locationTreeName: string;
    public isLoading$ = this.loaderService.isLoading$;

    // Table Template: Type actions column
    @ViewChild('actionsTemplate', { static: true }) actionsTemplate: TemplateRef<any>;

    public fields: Array<any> = [];
    // Table columns definition
    columns: Array<Column> = [];

    /* ------------------------------------------------------------------------------------------------------------------ */
    /*                                                     LIFE CYCLE                                                     */
    /* ------------------------------------------------------------------------------------------------------------------ */

    constructor(
        private objectService: ObjectService,
        private typeService: TypeService,
        private route: ActivatedRoute,
        private router: Router,
        private toastService: ToastService,
        private sidebarService: SidebarService,
        private _location: Location,
        private loaderService: LoaderService,
    ) {
        this.route.params.subscribe((params) => {
            this.objectID = params.publicID;
        });

        this.renderForm = new UntypedFormGroup({});

        this.commitForm = new UntypedFormGroup({
            comment: new UntypedFormControl('')
        });
    }


    public ngOnInit(): void {
        this.loaderService.show();
        this.objectService.getObject(this.objectID).pipe(finalize(() => this.loaderService.hide())).subscribe({
            next: (rr: RenderResult) => {
                this.renderResult = rr;
                this.activeState = this.renderResult.object_information.active;
            },
            error: e => {
                this.toastService.error(e?.error?.message)
            },
            complete: () => {
                this.objectService.getObject<CmdbObject>(this.objectID, true).subscribe(ob => {
                    this.objectInstance = ob;
                    // Snapshot the pristine state so editObject() can build a minimal PATCH diff.
                    this.originalSnapshot = JSON.parse(JSON.stringify(ob));
                });

                this.typeService.getType(this.renderResult.type_information.type_id).subscribe((value: CmdbType) => {
                    this.typeInstance = value;
                });
            }
        });
    }

    /* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    @HostListener('window:scroll', ['$event'])
    onWindowScroll($event) {
        const dialog = document.getElementById('object-form-action');

        if (document.body.scrollTop > 20 || document.documentElement.scrollTop > 20) {
            dialog.style.visibility = 'visible';
        } else {
            dialog.style.visibility = 'hidden';
        }
    }


    /**
     * Function to handle navigating back in the browser history
     */
    backClicked() {
        this._location.back();
    }


    public editObject(): void {
        this.renderForm.markAllAsTouched();

        // Guard against a save fired before the pristine object finished loading: without the
        // snapshot the diff cannot be trusted, so bail out instead of dereferencing undefined.
        if (!this.renderForm.valid || !this.objectInstance || !this.originalSnapshot) {
            return;
        }

        const { fields, sections } = this.collectFormValues();

        const { payload, hasChanges } = buildObjectPatchPayload({
            originalFields: this.originalSnapshot?.fields ?? [],
            editedFields: fields,
            originalSections: this.originalSnapshot?.multi_data_sections ?? [],
            editedSections: sections,
            comment: this.commitForm.get('comment')?.value
        });

        // Location is persisted through the object patch itself: dg_location rides along in the
        // fields and its label is carried by location_name. The backend creates, updates or
        // removes the location based on the dg_location value, so no separate call is needed.
        const locationChanged = this.applyLocationToPayload(payload);

        // Nothing changed on the object itself; only the active state may differ.
        if (!hasChanges && !locationChanged) {
            this.finalizeObjectUpdate();
            return;
        }

        this.loaderService.show();
        this.objectService.patchObject(this.objectID, payload)
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
                next: () => this.finalizeObjectUpdate(),
                error: e => {
                    this.toastService.error(e?.error?.message);
                    this.router.navigate(['/framework/object/type/' + this.objectInstance.type_id]);
                }
            });
    }


    public toggleChange() {
        this.activeState = this.activeState !== true;
        this.renderForm.markAsDirty();
    }


    /**
     * Folds the object's location into the patch payload. When a location is selected the
     * dg_location field is guaranteed to be present (so a rename-only change still reaches the
     * backend) and its label is attached as location_name. Returns whether the location has to
     * be sent, so a location-only change still triggers the patch.
     */
    private applyLocationToPayload(payload: ObjectPatchPayload): boolean {
        if (!this.selectedLocation || this.selectedLocation <= 0) {
            return false;
        }

        payload.fields = payload.fields ?? [];

        if (!payload.fields.some((field) => field.name === 'dg_location')) {
            payload.fields.push({ name: 'dg_location', value: this.selectedLocation });
        }

        payload.location_name = this.locationTreeName ?? '';

        return true;
    }


    /**
     * Walks the render form once, splitting the controls into object fields and
     * multi_data_section entries. dg_location is kept in the field list so it is diffed and
     * patched like any other field; the location label and the UI-only existence flag are
     * captured as a side effect and never sent as object fields.
     */
    private collectFormValues(): { fields: MultiDataSectionFieldValue[]; sections: MultiDataSectionEntry[] } {
        const fields: MultiDataSectionFieldValue[] = [];
        const sections: MultiDataSectionEntry[] = [];

        Object.keys(this.renderForm.value).forEach((key: string) => {
            const value = this.renderForm.value[key];

            if (key.startsWith('dg-mds-')) {
                if (value) {
                    if (!value.section_id) {
                        value.section_id = key.replace('dg-mds-', '');
                    }
                    sections.push(value);
                }
                return;
            }

            if (key === 'locationTreeName') {
                this.locationTreeName = value;
                return;
            }

            // UI-only helper control written onto the form value by the location field.
            if (key === 'locationForObjectExists') {
                return;
            }

            if (key === 'dg_location') {
                this.selectedLocation = value;
            }

            fields.push({ name: key, value: value === undefined || value === null ? '' : value });
        });

        return { fields, sections };
    }


    /**
     * Persists the active state and routes to the object view once the update is done.
     */
    private finalizeObjectUpdate(): void {
        this.loaderService.show();
        this.objectService.changeState(this.objectID, this.activeState)
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
                next: () => {
                    this.sidebarService.ReloadSideBarData();
                    this.toastService.success('Object was successfully updated!');
                    this.router.navigate(['/framework/object/view/' + this.objectID]);
                },
                error: e => {
                    this.toastService.error(e?.error?.message);
                }
            });
    }
}
