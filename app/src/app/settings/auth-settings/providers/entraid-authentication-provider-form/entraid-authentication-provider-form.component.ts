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
import { UntypedFormArray, UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';

import { AuthProvider } from '../../../../modules/auth/models/providers';
import { Group } from '../../../../management/models/group';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-entraid-authentication-provider-form',
    templateUrl: './entraid-authentication-provider-form.component.html',
    styleUrls: ['./entraid-authentication-provider-form.component.scss'],
    standalone: false
})
export class EntraIdAuthenticationProviderFormComponent {

    // The configuration form for the Entra ID auth provider
    public form: UntypedFormGroup;

    // The parent holder of the auth settings provider array
    public parent: UntypedFormArray;

    // Auth provider type
    public provider: AuthProvider;

    // List of possible mapping groups
    @Input() public groups: Array<Group> = [];

    // Password visibility toggle
    public showClientSecret: boolean = false;

    /* -------------------------------------------------- GETTER/SETTER ------------------------------------------------- */

    @Input('parent')
    public set Parent(form: UntypedFormArray) {
        this.parent = form;
        this.parent.insert(1, new UntypedFormGroup({
            class_name: new UntypedFormControl('EntraIdAuthenticationProvider'),
            config: this.form
        }));
    }

    @Input('provider')
    public set Provider(provider: AuthProvider) {
        this.provider = provider;
        if (provider && provider.config) {
            // Handle group mapping if exists
            if (provider.config.groups && provider.config.groups.mapping) {
                provider.config.groups.mapping.forEach((value: any, index: number) => {
                    const formGroup = new UntypedFormGroup({
                        group_name: new UntypedFormControl(value.group_name),
                        group_id: new UntypedFormControl(value.group_id)
                    });
                    this.groupMappingControl.insert(index, formGroup);
                });
            }
            this.form.patchValue(provider.config);
        }
    }

    // Entra ID groups control
    public get groupsControl(): UntypedFormGroup {
        return this.form.get('groups') as UntypedFormGroup;
    }

    // Nested groups mapping form array
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
            tenant_id: new UntypedFormControl('', [Validators.required]),
            client_id: new UntypedFormControl('', [Validators.required]),
            client_secret: new UntypedFormControl('', [Validators.required]),
            redirect_uri: new UntypedFormControl('', [Validators.required]),
            groups: new UntypedFormGroup({
                active: new UntypedFormControl(false),
                mapping: new UntypedFormArray([])
            })
        });
    }

    /* ------------------------------------------------- HELPER METHODS -------------------------------------------------- */

    /**
     * Toggle client secret visibility
     */
    public toggleClientSecretVisibility(): void {
        this.showClientSecret = !this.showClientSecret;
    }

    /**
     * Add a new group mapping entry
     */
    public addGroupMapping(): void {
        const formGroup = new UntypedFormGroup({
            group_name: new UntypedFormControl(''),
            group_id: new UntypedFormControl(null)
        });
        this.groupMappingControl.push(formGroup);
    }

    /**
     * Remove a group mapping entry
     */
    public removeGroupMapping(index: number): void {
        this.groupMappingControl.removeAt(index);
    }
}
