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

import { CoreModule } from '../../core/core.module';
import { LayoutModule } from '../../layout/layout.module';
import { AuthModule } from '../../modules/auth/auth.module';

import { LicenseManagementRoutingModule } from './license-management-routing.module';
import { LicenseManagementComponent } from './license-management.component';
import { LicenseStatusBadgeComponent } from './components/license-status-badge/license-status-badge.component';
import { LicenseStatusBannerComponent } from './components/license-status-banner/license-status-banner.component';
import { LicenseOverviewCardComponent } from './components/license-overview-card/license-overview-card.component';
import { LicenseFeatureCatalogComponent } from './components/license-feature-catalog/license-feature-catalog.component';
import { LicenseCatalogModalComponent } from './components/license-catalog-modal/license-catalog-modal.component';
import { LicenseActivationWorkflowComponent } from './components/license-activation-workflow/license-activation-workflow.component';
import { LicenseImportComponent } from './components/license-import/license-import.component';
/* ------------------------------------------------------------------------------------------------------------------ */

@NgModule({
  declarations: [
    LicenseManagementComponent,
    LicenseStatusBadgeComponent,
    LicenseStatusBannerComponent,
    LicenseOverviewCardComponent,
    LicenseFeatureCatalogComponent,
    LicenseCatalogModalComponent,
    LicenseActivationWorkflowComponent,
    LicenseImportComponent
  ],
  imports: [
    CommonModule,
    LicenseManagementRoutingModule,
    CoreModule,
    LayoutModule,
    AuthModule
  ]
})
export class LicenseManagementModule {}
