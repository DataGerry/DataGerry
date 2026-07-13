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
import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule } from '@angular/forms';

import { DndModule } from 'ngx-drag-drop';

import { AuthSettingsRoutingModule } from './auth-settings-routing.module';
import { RenderModule } from '../../framework/render/render.module';

import { ActiveProvidersPipe } from './active-providers.pipe';

import { AuthSettingsComponent } from './auth-settings.component';
import { LdapAuthenticationProviderFormComponent } from './providers/ldap-authentication-provider-form/ldap-authentication-provider-form.component';
import { LocalAuthenticationProviderFormComponent } from './providers/local-authentication-provider-form/local-authentication-provider-form.component';
import { LdapProviderFormGroupMappingComponent } from './providers/ldap-authentication-provider-form/ldap-provider-form-group-mapping/ldap-provider-form-group-mapping.component';
import { OidcAuthenticationProviderFormComponent } from './providers/oidc-authentication-provider-form/oidc-authentication-provider-form.component';
/* ------------------------------------------------------------------------------------------------------------------ */

@NgModule({
    declarations: [
        AuthSettingsComponent,
        ActiveProvidersPipe,
        LdapAuthenticationProviderFormComponent,
        LocalAuthenticationProviderFormComponent,
        LdapProviderFormGroupMappingComponent,
        OidcAuthenticationProviderFormComponent
    ],
    imports: [
        CommonModule,
        AuthSettingsRoutingModule,
        ReactiveFormsModule,
        RenderModule,
        DndModule
    ]
})
export class AuthSettingsModule {}
