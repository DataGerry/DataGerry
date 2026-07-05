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

import { first } from 'rxjs';

import { ApiCallService } from '../../../../services/api-call.service';
import { ToastService } from '../../../../layout/toast/toast.service';

import { AuthProvider } from '../../../../modules/auth/models/providers';
import { Group } from '../../../../management/models/group';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-oidc-authentication-provider-form',
    templateUrl: './oidc-authentication-provider-form.component.html',
    styleUrls: ['./oidc-authentication-provider-form.component.scss'],
    standalone: false
})
export class OidcAuthenticationProviderFormComponent {

    public form: UntypedFormGroup;
    public parent: UntypedFormArray;
    public provider: AuthProvider;

    public discovering = false;

    @Input() public groups: Array<Group> = [];

    /* -------------------------------------------------- GETTER/SETTER ------------------------------------------------- */

    @Input('parent')
    public set Parent(form: UntypedFormArray) {
        this.parent = form;
        this.parent.insert(2, new UntypedFormGroup({
            class_name: new UntypedFormControl('OpenIDConnectAuthenticationProvider'),
            config: this.form
        }));
    }

    @Input('provider')
    public set Provider(provider: AuthProvider) {
        this.provider = provider;

        if (provider?.config) {
            const mapping = provider.config.groups_mapping?.mapping;
            if (mapping) {
                mapping.forEach((value: any, index: number) => {
                    this.groupMappingControl.insert(index, new UntypedFormGroup({
                        oidc_group: new UntypedFormControl(value.oidc_group),
                        group_id: new UntypedFormControl(value.group_id)
                    }));
                });
            }

            // scopes/frontend_origins are stored as arrays but edited as comma-separated text.
            this.form.patchValue({
                ...provider.config,
                scopes: this.toCsv(provider.config.scopes),
                frontend_origins: this.toCsv(provider.config.frontend_origins)
            });
        }
    }

    public get claimsMappingControl(): UntypedFormGroup {
        return this.form.get('claims_mapping') as UntypedFormGroup;
    }

    public get groupsMappingControl(): UntypedFormGroup {
        return this.form.get('groups_mapping') as UntypedFormGroup;
    }

    public get groupMappingControl(): UntypedFormArray {
        return this.groupsMappingControl.get('mapping') as UntypedFormArray;
    }

    /* ------------------------------------------------------------------------------------------------------------------ */
    /*                                                     LIFE CYCLE                                                     */
    /* ------------------------------------------------------------------------------------------------------------------ */

    constructor(private api: ApiCallService, private toast: ToastService) {
        this.form = new UntypedFormGroup({
            active: new UntypedFormControl(false),
            jit_provisioning: new UntypedFormControl(true),
            default_group: new UntypedFormControl(null),
            auto_redirect: new UntypedFormControl(false),
            discovery_url: new UntypedFormControl(''),
            issuer: new UntypedFormControl(''),
            authorization_endpoint: new UntypedFormControl(''),
            token_endpoint: new UntypedFormControl(''),
            userinfo_endpoint: new UntypedFormControl(''),
            jwks_uri: new UntypedFormControl(''),
            client_id: new UntypedFormControl(''),
            client_secret: new UntypedFormControl(''),
            token_endpoint_auth_method: new UntypedFormControl('client_secret_basic'),
            scopes: new UntypedFormControl('openid, profile, email'),
            redirect_uri: new UntypedFormControl(''),
            frontend_origins: new UntypedFormControl(''),
            claims_mapping: new UntypedFormGroup({
                user_name: new UntypedFormControl('preferred_username'),
                email: new UntypedFormControl('email'),
                first_name: new UntypedFormControl('given_name'),
                last_name: new UntypedFormControl('family_name'),
                groups: new UntypedFormControl('groups')
            }),
            groups_mapping: new UntypedFormGroup({
                active: new UntypedFormControl(false),
                mapping: new UntypedFormArray([])
            })
        });
    }

    /* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

    public addGroupMapping(): void {
        this.groupMappingControl.push(new UntypedFormGroup({
            oidc_group: new UntypedFormControl(''),
            group_id: new UntypedFormControl(null)
        }));
    }


    /**
     * Server-side discovery fetch (avoids browser CORS to the IdP). Populates the endpoint fields.
     */
    public onDiscover(): void {
        const discoveryUrl = this.form.get('discovery_url')?.value;

        if (!discoveryUrl) {
            this.toast.error('Please enter a discovery URL first');
            return;
        }

        this.discovering = true;
        this.api.callPost('auth/oidc/discover', { discovery_url: discoveryUrl })
            .pipe(first())
            .subscribe({
                next: (response) => {
                    const doc = response?.body ?? response;
                    this.form.patchValue({
                        issuer: doc.issuer,
                        authorization_endpoint: doc.authorization_endpoint,
                        token_endpoint: doc.token_endpoint,
                        userinfo_endpoint: doc.userinfo_endpoint,
                        jwks_uri: doc.jwks_uri
                    });
                    this.discovering = false;
                    this.toast.success('Endpoints resolved from discovery document');
                },
                error: (err) => {
                    this.discovering = false;
                    this.toast.error(err?.error?.message || 'Discovery failed');
                }
            });
    }


    private toCsv(value: string | Array<string>): string {
        return Array.isArray(value) ? value.join(', ') : (value || '');
    }
}
