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
import { Component, Input } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup } from '@angular/forms';

import { ReplaySubject, Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

import { CmdbType } from '../../models/cmdb-type';
import { CmdbMode } from '../../modes.enum';
import { Group } from '../../../management/models/group';
import { User } from '../../../management/models/user';
import { nameConvention } from '../../../layout/directives/name.directive';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    template: ``,
    standalone: false,
    host: { 'data-config-edit-base': 'type' }
})
export abstract class ConfigEditBaseComponent {

    protected abstract subscriber: ReplaySubject<void>;

    // Cmdb modes for template usage
    public MODES = CmdbMode;

    public abstract nameControl: UntypedFormControl;
    public abstract labelControl: UntypedFormControl;

    @Input() public fieldSectionType: string;
    @Input() public hiddenStatus: boolean;
    @Input() public mode: CmdbMode = CmdbMode.Create;
    @Input() public form: UntypedFormGroup;
    @Input() public data: any;
    @Input() public sections: Array<any>;
    @Input() public fields: Array<any> = [];
    @Input() public types: Array<CmdbType> = [];
    @Input() public groups: Array<Group> = [];
    @Input() public users: Array<User> = [];

    public fieldChanges$ = new Subject();

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    protected constructor() {
        this.form = new UntypedFormGroup({});
    }

/* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

    protected disableControlOnEdit(control: UntypedFormControl): void {
        if (this.mode === CmdbMode.Edit) {
            this.updateAndClearValidators(control);
            control.disable({ onlySelf: false, emitEvent: false });
        }
    }


    protected disableControlsOnGlobal(control: UntypedFormControl): void {
        if (this.mode === CmdbMode.Global) {
            this.updateAndClearValidators(control)
            control.disable({ onlySelf: false, emitEvent: false });
        }
    }


    public onInputChange(change: any, idx: string): void {
        this.data[idx] = change;
    }


    protected validateNameLabelControl(nameControl: UntypedFormControl,
                                        labelControl: UntypedFormControl,
                                        subscriber: ReplaySubject<void>): void {
        this.disableControlOnEdit(nameControl);

        if (this.mode === CmdbMode.Create) {
            labelControl.valueChanges.pipe(takeUntil(subscriber)).subscribe((changes: string) => {

                if (!nameControl.touched) {
                    nameControl.setValue(nameConvention(changes), { emitEvent: true });
                }
            });
        }
    }


    protected patchData(data: any, form: UntypedFormGroup): void {
        form.patchValue(data);

        if (this.mode === CmdbMode.Edit) {
            this.form.markAllAsTouched();
        }
    }


    private updateAndClearValidators(control: UntypedFormControl) {
        control.clearValidators();
        control.updateValueAndValidity();
    }
}
