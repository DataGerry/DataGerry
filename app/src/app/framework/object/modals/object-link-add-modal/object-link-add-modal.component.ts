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
import { Component, Input, OnDestroy, OnInit } from '@angular/core';
import { AbstractControl, UntypedFormControl, UntypedFormGroup, ValidatorFn, Validators } from '@angular/forms';

import { ReplaySubject } from 'rxjs';

import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { checkObjectExistsValidator, ObjectService } from '../../../services/object.service';

import { RenderResult } from '../../../models/cmdb-render';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    templateUrl: './object-link-add-modal.component.html',
    styleUrls: ['./object-link-add-modal.component.scss'],
    standalone: false
})
export class ObjectLinkAddModalComponent implements OnInit, OnDestroy {
    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();
    public form: UntypedFormGroup;
    public primaryResult: RenderResult;


    @Input('primaryResult')
    public set primaryRenderResult(result: RenderResult) {
        this.primaryResult = result;
        this.form.get('primary').setValue(this.primaryResult.object_information.object_id);
    }


    constructor(public activeModal: NgbActiveModal, private objectService: ObjectService) {
        this.form = new UntypedFormGroup({
            primary: new UntypedFormControl(null, [Validators.required]),
            secondary: new UntypedFormControl('', [Validators.required],
                [checkObjectExistsValidator(objectService)])
        });
    }


    public ngOnInit(): void {
        this.form.get('secondary').setValidators(this.sameIDValidator());
        this.form.get('secondary').updateValueAndValidity();
    }


    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
    }


    public get primary(): UntypedFormControl {
        return this.form.get('primary') as UntypedFormControl;
    }


    public get secondary(): UntypedFormControl {
        return this.form.get('secondary') as UntypedFormControl;
    }


    private sameIDValidator(): ValidatorFn {
        return (control: AbstractControl): { [key: string]: any } | null => {
            const same = control.value === this.primary.value;
            return same ? { sameID: true } : null;
        };
    }


    public async onSave() {
        const formData = this.form.getRawValue();
        if (!this.secondary.invalid) {
            this.activeModal.close(formData);
        }
    }
}