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
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { MatMenuModule } from '@angular/material/menu';
import { MatIconModule } from '@angular/material/icon';

import { NgSelectModule } from '@ng-select/ng-select';
import { NgbTooltipModule } from '@ng-bootstrap/ng-bootstrap';
import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';
import { ArchwizardModule } from '@rg-software/angular-archwizard';
import { QRCodeComponent } from 'angularx-qrcode';
import { NgxPaginationModule } from 'ngx-pagination';

import { ObjectRoutingModule } from './object-routing.module';
import { LayoutModule } from '../../layout/layout.module';
import { RenderModule } from '../render/render.module';
import { AuthModule } from '../../modules/auth/auth.module';
import { UsersModule } from '../../management/users/users.module';
import { TableModule } from '../../layout/table/table.module';

import { ObjectComponent } from './object.component';
import { ObjectViewComponent } from './object-view/object-view.component';
import { ObjectHeaderComponent } from './components/object-header/object-header.component';
import { ObjectQrComponent } from './components/object-qr/object-qr.component';
import { ObjectSummaryComponent } from './components/object-summary/object-summary.component';
import { ObjectExternalsComponent } from './components/object-externals/object-externals.component';
import { ObjectAddComponent } from './object-add/object-add.component';
import { ObjectFooterComponent } from './object-view/object-footer/object-footer.component';
import { IpamSupernetOverviewComponent } from './object-view/ipam-overview/ipam-supernet-overview/ipam-supernet-overview.component';
import { IpamSubnetOverviewComponent } from './object-view/ipam-overview/ipam-subnet-overview/ipam-subnet-overview.component';
import { IpamIpTableComponent } from './object-view/ipam-overview/components/ipam-ip-table/ipam-ip-table.component';
import { IpamIpDistributionComponent } from './object-view/ipam-overview/components/ipam-ip-distribution/ipam-ip-distribution.component';
import { IpamTypeDistributionComponent } from './object-view/ipam-overview/components/ipam-type-distribution/ipam-type-distribution.component';
import { ObjectActionsComponent } from './components/object-actions/object-actions.component';
import { ObjectViewMetaComponent } from './components/object-view-meta/object-view-meta.component';
import { ObjectEditComponent } from './object-edit/object-edit.component';
import { ObjectViewRenderComponent } from './components/object-view-render/object-view-render.component';
import { ObjectCopyComponent } from './object-copy/object-copy.component';
import { ObjectTypeLabelComponent } from './components/object-type-label/object-type-label.component';
import { ObjectLogListComponent } from './components/object-log-list/object-log-list.component';
import { ObjectLogComponent } from './object-log/object-log.component';
import { ObjectLogChangeViewComponent } from './components/object-log-list/object-log-change-view/object-log-change-view.component';
import { ObjectLogUserComponent } from './components/object-log-list/object-log-user/object-log-user.component';
import { ObjectDocsComponent } from './components/object-docs/object-docs.component';
import { ObjectAttachmentsComponent } from './components/object-attachments/object-attachments.component';
import { ObjectsByTypeComponent } from './objects-by-type/objects-by-type.component';
import { ObjectDeleteModalComponent } from './modals/object-delete-modal/object-delete-modal.component';
import { ObjectsDeleteModalComponent } from './modals/objects-delete-modal/objects-delete-modal.component';
import { ObjectTableActionsComponent } from './components/object-table-actions/object-table-actions.component';
import { ObjectTableHeadComponent } from './components/object-table-head/object-table-head.component';
import { ObjectReferencesTableComponent } from './components/object-references/object-references-table/object-references-table.component';
import { ObjectReferencesComponent } from './components/object-references/object-references.component';
import { ObjectReferencesByTypeComponent } from './components/object-references/object-references-by-type/object-references-by-type.component';
import { ObjectReferencesTypeColumnComponent } from './components/object-references/object-references-type-column/object-references-type-column.component';
import { ObjectBulkChangeComponent } from './object-bulk-change/object-bulk-change.component';
import { ObjectBulkChangeEditorComponent } from './object-bulk-change/object-bulk-change-editor/object-bulk-change-editor.component';
import { ObjectBulkChangePreviewComponent } from './object-bulk-change/object-bulk-change-preview/object-bulk-change-preview.component';
import { ObjectBulkChangeFailedComponent } from './object-bulk-change/object-bulk-change-complete/object-bulk-change-failed/object-bulk-change-failed.component';
import { ObjectBulkChangeCompleteComponent } from './object-bulk-change/object-bulk-change-complete/object-bulk-change-complete.component';
import { CoreModule } from 'src/app/core/core.module';
import { RelationRoleDialogComponent } from './object-view/relation-role-dialog/relation-role-dialog.component';
import { RelationLogListComponent } from './components/object-relation-log-list/relation-log-list.component';
import { ChangesModalComponent } from './modals/object-relation-changes-modal/changes-modal.component';
import { RiskAssessmentModule } from 'src/app/toolbox/isms/risk-assessment/risk-assesment.module';
import { GraphEditorComponent } from './object-view/graph-editor/graph-editor.component';
import { NodeDetailsModalComponent } from './object-view/graph-editor/modals/node-details/node-details-modal.component';
import { ProfileManagerModalComponent } from './object-view/graph-editor/modals/profile-manager/profile-manager-modal.component';
import { ProfileDeleteModalComponent } from './object-view/graph-editor/modals/profile-delete/profile-delete-modal.component';
import { ConnectionDetailsModalComponent } from './object-view/graph-editor/modals/connection-details/connection-details-modal.component';
/* ------------------------------------------------------------------------------------------------------------------ */

@NgModule({
    declarations: [
        ObjectViewComponent,
        ObjectHeaderComponent,
        ObjectQrComponent,
        ObjectSummaryComponent,
        ObjectExternalsComponent,
        ObjectAddComponent,
        ObjectFooterComponent,
        IpamSupernetOverviewComponent,
        IpamSubnetOverviewComponent,
        IpamIpTableComponent,
        IpamIpDistributionComponent,
        IpamTypeDistributionComponent,
        ObjectActionsComponent,
        ObjectViewRenderComponent,
        ObjectViewMetaComponent,
        ObjectEditComponent,
        ObjectCopyComponent,
        ObjectTypeLabelComponent,
        ObjectLogListComponent,
        ObjectLogComponent,
        ObjectLogChangeViewComponent,
        ObjectLogUserComponent,
        ObjectBulkChangeComponent,
        ObjectBulkChangePreviewComponent,
        ObjectBulkChangeEditorComponent,
        ObjectBulkChangePreviewComponent,
        ObjectDocsComponent,
        ObjectAttachmentsComponent,
        ObjectsByTypeComponent,
        ObjectTableActionsComponent,
        ObjectDeleteModalComponent,
        ObjectsDeleteModalComponent,
        ObjectTableHeadComponent,
        ObjectReferencesTableComponent,
        ObjectReferencesComponent,
        ObjectReferencesByTypeComponent,
        ObjectComponent,
        ObjectReferencesTypeColumnComponent,
        ObjectBulkChangeFailedComponent,
        ObjectBulkChangeCompleteComponent,
        RelationRoleDialogComponent,
        RelationLogListComponent,
        ChangesModalComponent,
        GraphEditorComponent,
        NodeDetailsModalComponent,
        ProfileManagerModalComponent,
        ProfileDeleteModalComponent,
        ConnectionDetailsModalComponent
       ],
    imports: [
        CommonModule,
        ObjectRoutingModule,
        AuthModule,
        LayoutModule,
        FormsModule,
        ReactiveFormsModule,
        NgSelectModule,
        NgbTooltipModule,
        FontAwesomeModule,
        ArchwizardModule,
        RenderModule,
        UsersModule,
        TableModule,
        NgxPaginationModule,
        MatMenuModule,
        MatIconModule,
        CoreModule,
        RiskAssessmentModule,
        QRCodeComponent],
    exports: [
        ObjectViewRenderComponent,
        ObjectTableActionsComponent,
        ObjectLogChangeViewComponent,
        ObjectLogUserComponent
    ]
})
export class ObjectModule {}
