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
import { Component, OnDestroy, OnInit, ChangeDetectorRef } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

import { ReplaySubject } from 'rxjs';
import { distinctUntilChanged, takeUntil } from 'rxjs/operators';

import { ToastService } from '../../../../layout/toast/toast.service';
import { TypeService } from '../../../services/type.service';
import { ValidationService } from 'src/app/framework/builder/services/validation.service';

import { ConfigEditBaseComponent } from '../config.edit';
import { CmdbType } from '../../../models/cmdb-type';
import { CollectionParameters } from '../../../../services/models/api-parameter';
import { nameConvention } from '../../../../layout/directives/name.directive';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-location-field-edit',
    templateUrl: './location-field-edit.component.html',
    styleUrls: ['./location-field-edit.component.scss'],
    standalone: false
})
export class LocationFieldEditComponent extends ConfigEditBaseComponent implements OnInit, OnDestroy {

    // Component un-subscriber.
    protected subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    public nameControl: UntypedFormControl = new UntypedFormControl('');
    public labelControl: UntypedFormControl = new UntypedFormControl('', Validators.required);
    public typeControl: UntypedFormControl = new UntypedFormControl(undefined);
    public requiredControl: UntypedFormControl = new UntypedFormControl(false);
    public summaryControl: UntypedFormControl = new UntypedFormControl(undefined);
    public selectableAsParentControl = new UntypedFormControl(false);

    public referenceGroup: UntypedFormGroup = new UntypedFormGroup({ type_id: this.typeControl });

    public typesParams: CollectionParameters = {
        filter: undefined, limit: 0, sort: 'public_id', order: 1, page: 1
    };

    public selectable_as_parent: boolean;
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


    ngOnInit(): void {
        this.setDraggable("false");
        this.form.addControl('required', this.requiredControl);
        this.form.addControl('name', this.nameControl);
        this.form.addControl('label', this.labelControl);
        this.form.addControl('selectable_as_parent', this.selectableAsParentControl);
      
        this.disableControlOnEdit(this.nameControl);
        this.patchData(this.data, this.form);

        // Keep the field label in sync with the shared field object now that the
        // template no longer uses ngModel alongside the reactive formControl.
        this.labelControl.valueChanges
          .pipe(takeUntil(this.subscriber))
          .subscribe((value: string) => {
            this.data.label = value;
          });

        this.initialValue = this.nameControl.value;
      
        // Get the initial value from the TYPE (edit mode), fallback to field (create), then to false.
        const initialSelectable =
          this.data?.selectable_as_parent ??
          this.activeRoute.snapshot?.data?.type?.selectable_as_parent ??
          false;
      
        // Patch once without firing valueChanges
        this.selectableAsParentControl.setValue(!!initialSelectable, { emitEvent: false });
      
        if (this.form.controls['label'].invalid) this.isValid$ = false;
      
        // Let the parent know the current value even if the user never touches it
        this.fieldChanges$.next({
          newValue: this.selectableAsParentControl.value,
          inputName: 'selectable_as_parent',
          fieldName: this.nameControl.value,
          previousName: this.initialValue,
          elementType: 'location'
        });
      
        // Normal change propagation if the user toggles
        this.selectableAsParentControl.valueChanges
          .pipe(distinctUntilChanged(), takeUntil(this.subscriber))
          .subscribe((value: boolean) => {
            this.fieldChanges$.next({
              newValue: value,
              inputName: 'selectable_as_parent',
              fieldName: this.nameControl.value,
              previousName: this.initialValue,
              elementType: 'location'
            });
            this.cd.markForCheck();
          });
      }
      
      
      


    public ngOnDestroy(): void {
        this.setDraggable("true");
        this.subscriber?.next();
        this.subscriber?.complete();
        this.validationService?.cleanup();
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
