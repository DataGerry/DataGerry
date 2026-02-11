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
import { UntypedFormArray, UntypedFormControl, UntypedFormGroup } from '@angular/forms';

import { AuthProvider } from '../../../../modules/auth/models/providers';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-local-authentication-provider-form',
    templateUrl: './local-authentication-provider-form.component.html',
    styleUrls: ['./local-authentication-provider-form.component.scss'],
    standalone: false
})
export class LocalAuthenticationProviderFormComponent {

    public form: UntypedFormGroup;
    public parent: UntypedFormArray;
    public provider: AuthProvider;

/* -------------------------------------------------- GETTER/SETTER ------------------------------------------------- */

    @Input('parent')
    public set Parent(form: UntypedFormArray) {
        this.parent = form;
        this.parent.insert(0, new UntypedFormGroup({
            class_name: new UntypedFormControl('LocalAuthenticationProvider'),
            config: this.form
        }));
    }


    @Input('provider')
    public set Provider(provider: AuthProvider) {
        this.provider = provider;
        this.form.patchValue(provider.config);
    }


    constructor() {
        this.form = new UntypedFormGroup({
            active: new UntypedFormControl()
        });

        this.form.get('active').disable({onlySelf: true});
    }
}