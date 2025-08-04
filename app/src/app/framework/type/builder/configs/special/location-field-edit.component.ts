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
import { Component, OnDestroy, OnInit, ChangeDetectorRef } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

import { ReplaySubject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

import { ToastService } from '../../../../../layout/toast/toast.service';
import { TypeService } from '../../../../services/type.service';
import { ValidationService } from '../../../services/validation.service';

import { ConfigEditBaseComponent } from '../config.edit';
import { CmdbType } from '../../../../models/cmdb-type';
import { CollectionParameters } from '../../../../../services/models/api-parameter';
import { nameConvention } from '../../../../../layout/directives/name.directive';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-location-field-edit',
    templateUrl: './location-field-edit.component.html',
    styleUrls: ['./location-field-edit.component.scss'],
})
export class LocationFieldEditComponent extends ConfigEditBaseComponent implements OnInit, OnDestroy {

    // Component un-subscriber.
    protected subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    public nameControl: UntypedFormControl = new UntypedFormControl('');
    public labelControl: UntypedFormControl = new UntypedFormControl('', Validators.required);
    public typeControl: UntypedFormControl = new UntypedFormControl(undefined);
    public requiredControl: UntypedFormControl = new UntypedFormControl(false);
    public summaryControl: UntypedFormControl = new UntypedFormControl(undefined);

    public referenceGroup: UntypedFormGroup = new UntypedFormGroup({ type_id: this.typeControl });

    public typesParams: CollectionParameters = {
        filter: undefined, limit: 0, sort: 'public_id', order: 1, page: 1
    };

    public selectable_as_parent: boolean = true;
    public currentTypeID: number;

    private initialValue: string;
    isValid$ = true;

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(
        private typeService: TypeService,
        private toast: ToastService,
        private cd: ChangeDetectorRef,
        private activeRoute: ActivatedRoute,
        private validationService: ValidationService) {

        super();
    }


    public ngOnInit(): void {
        this.setDraggable("false");
        this.form.addControl('required', this.requiredControl);
        this.form.addControl('name', this.nameControl);
        this.form.addControl('label', this.labelControl);

        this.currentTypeID = this.activeRoute.data['_value']?.type?.public_id;
        this.disableControlOnEdit(this.nameControl);
        this.patchData(this.data, this.form);

        if (this.currentTypeID) {
            this.triggerAPICall();
        }

        this.initialValue = this.nameControl.value;

        if (this.form.controls['label'].invalid) {
            this.isValid$ = false;
        }
    }


    public ngOnDestroy(): void {
        this.setDraggable("true");
        this.subscriber?.next();
        this.subscriber?.complete();
        this.validationService?.cleanup();
    }


    /* ---------------------------------------------------- API CALLS --------------------------------------------------- */

    public triggerAPICall() {
        this.typeService.getType(this.currentTypeID).pipe(takeUntil(this.subscriber))
            .subscribe({
                next: (apiResponse: CmdbType) => {
                    this.selectable_as_parent = apiResponse.selectable_as_parent;
                    this.cd.markForCheck();
                },
                error: (error) => this.toast.error(error?.error?.message)
            });
    }

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    onInputChange(event: any) {
        for (let item in this.form.controls) {
            this.hasValidator(item);
        }

        this.validationService.setIsValid(this.initialValue, this.isValid$);
        this.isValid$ = true;
    }


    public hasValidator(control: string): void {
        if (this.form.controls[control].hasValidator(Validators.required)) {
            let valid = this.form.controls[control].valid;
            this.isValid$ = this.isValid$ && valid;
        }
    }


    public onNameChange(name: string) {
        this.data.name = nameConvention(name);
    }


    private setSelectableAsParent(value: boolean): void {
        if (this.activeRoute.snapshot.data.type?.selectable_as_parent) {
            this.activeRoute.snapshot.data.type.selectable_as_parent = value;
        }
    }


    public updateSelectableAsParent() {
        this.selectable_as_parent = !this.selectable_as_parent;
        this.setSelectableAsParent(this.selectable_as_parent);
        this.cd.markForCheck();
    }


    //TODO: this is just a work around and need to be set with proper angular code 
    //sets the special control location to not draggable when there is already a location present
    private setDraggable(isDraggable: string): void {
        let opacity: string = isDraggable == "true" ? "1.0" : "0.5";

        //this only works if the special control "location" is the 2nd element
        let specialControlLocation: Element = document.getElementById('specialControls').getElementsByClassName('list-group-item')[1];
        specialControlLocation.setAttribute('draggable', isDraggable);
        (specialControlLocation as HTMLElement).style.opacity = opacity;
    }
}
