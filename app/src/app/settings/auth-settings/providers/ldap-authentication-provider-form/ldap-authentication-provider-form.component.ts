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
import { Component, Input } from '@angular/core';
import { UntypedFormArray, UntypedFormControl, UntypedFormGroup } from '@angular/forms';

import { AuthProvider } from '../../../../modules/auth/models/providers';
import { Group } from '../../../../management/models/group';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-ldap-authentication-provider-form',
    templateUrl: './ldap-authentication-provider-form.component.html',
    styleUrls: ['./ldap-authentication-provider-form.component.scss'],
    standalone: false
})
export class LdapAuthenticationProviderFormComponent {

    // The configuration form for the ldap auth provider
    public form: UntypedFormGroup;

    // The parent holder of the auth settings provider array
    public parent: UntypedFormArray;

    // Auth provider type
    public provider: AuthProvider;

    // List of a possible mapping groups
    @Input() public groups: Array<Group> = [];

/* -------------------------------------------------- GETTER/SETTER ------------------------------------------------- */

    @Input('parent')
    public set Parent(form: UntypedFormArray) {
        this.parent = form;
        this.parent.insert(1, new UntypedFormGroup({
            class_name: new UntypedFormControl('LdapAuthenticationProvider'),
            config: this.form
        }));
    }

    @Input('provider')
    public set Provider(provider: AuthProvider) {
        this.provider = provider;
        if (provider) {
            provider.config.groups.mapping.forEach((value, index) => {
                const formGroup = new UntypedFormGroup({
                    group_dn: new UntypedFormControl(value.group_dn),
                    group_id: new UntypedFormControl(value.group_id)
                });
                this.groupMappingControl.insert(index, formGroup);
            });
        }

        this.form.patchValue(provider.config);
    }

    // Ldap server config control
    public get serverConfigControl(): UntypedFormGroup {
        return this.form.get('server_config') as UntypedFormGroup;
    }

    // Ldap connection config control
    public get connectionConfigControl(): UntypedFormGroup {
        return this.form.get('connection_config') as UntypedFormGroup;
    }

    // Ldap user search control
    public get searchControl(): UntypedFormGroup {
        return this.form.get('search') as UntypedFormGroup;
    }

    // Ldap groups control
    public get groupsControl(): UntypedFormGroup {
        return this.form.get('groups') as UntypedFormGroup;
    }

    // Nested ldap groups mapping form array
    public get groupMappingControl(): UntypedFormArray {
        return this.groupsControl.get('mapping') as UntypedFormArray;
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    constructor() {
        this.form = new UntypedFormGroup({
            active: new UntypedFormControl(false),
            default_group: new UntypedFormControl(null),
            server_config: new UntypedFormGroup({
                host: new UntypedFormControl(),
                port: new UntypedFormControl(null),
                use_ssl: new UntypedFormControl(false)
             }),
            connection_config: new UntypedFormGroup({
                user: new UntypedFormControl(),
                password: new UntypedFormControl(),
                version: new UntypedFormControl(null)
            }),
            search: new UntypedFormGroup({
                basedn: new UntypedFormControl(),
                searchfilter: new UntypedFormControl()
            }),
            groups: new UntypedFormGroup({
                active: new UntypedFormControl(false),
                searchfiltergroup: new UntypedFormControl(),
                mapping: new UntypedFormArray([])
            })
        });
    }
}