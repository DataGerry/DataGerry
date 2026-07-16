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
import { RouterModule } from '@angular/router';

import { NgbModule } from '@ng-bootstrap/ng-bootstrap';
import { NgSelectModule } from '@ng-select/ng-select';
import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';

import { RenderElementComponent } from './render-element/render-element.component';
import { TextComponent } from './fields/text/text.component';
import { RenderComponent } from './render.component';
import { PasswordComponent } from './fields/text/password.component';
import { RadioComponent } from './fields/choice/radio.component';
import { SelectComponent } from './fields/choice/select.component';
import { RefComponent } from './fields/special/ref.component';
import { LocationComponent } from './fields/special/location.component';
import { CheckboxComponent } from './fields/choice/checkbox.component';
import { TextareaComponent } from './fields/textarea/textarea.component';
import { ModeErrorComponent } from './components/mode-error/mode-error.component';
import { RenderErrorComponent } from './components/render-error/render-error.component';
import { TextSimpleComponent } from './simple/text/text-simple.component';
import { PasswordSimpleComponent } from './simple/text/password-simple.component';
import { CheckboxSimpleComponent } from './simple/choice/checkbox-simple.component';
import { RadioSimpleComponent } from './simple/choice/radio-simple.component';
import { SelectSimpleComponent } from './simple/choice/select-simple.component';
import { RefSimpleComponent } from './simple/special/ref-simple.component';
import { LocationSimpleComponent } from './simple/special/location-simple.component';
import { DateComponent } from './fields/date/date.component';
import { DateSimpleComponent } from './simple/date/date-simple.component';
import { NumberComponent } from './fields/math/number.component';
import { InputAppendsComponent } from './components/input-appends/input-appends.component';
import { ObjectBulkInputAppendsComponent } from './components/object-bulk-input-appends/object-bulk-input-appends.component';
import { RenderFieldComponent } from './fields/components.fields';
import { RefSectionComponent } from './fields/section/ref-section.component';
import { FieldSectionComponent } from './sections/field-section/field-section.component';
import { MultiDataSectionComponent } from './sections/multi-data-section/multi-data-section.component';
import { BaseSectionComponent } from './sections/base-section/base-section.component';
import { ReferenceSectionComponent } from './sections/reference-section/reference-section.component';
import { SectionsFactoryComponent } from './sections/sections-factory/sections-factory.component';
import { DateFormatterPipe } from '../../layout/pipes/date-formatter.pipe';
import { RefSectionSimpleComponent } from './simple/special/ref-section-simple.component';
import { TableModule } from 'src/app/layout/table/table.module';
import { MultiDataActionsComponent } from './sections/multi-data-actions/multi-data-actions.component';
import { SubnetNetworkRangeValidatorDirective } from './special-types/subnet/directives/subnet-network-range-validator.directive';
import { SupernetNetworkRangeValidatorDirective } from './special-types/supernet/directives/supernet-network-range-validator.directive';
import { IPAM_INTERFACE_PROVIDERS } from './special-types/ipam-interface/ipam-interface.providers';
import { IpamSubnetSelectComponent } from './special-types/ipam-interface/components/ipam-subnet-select/ipam-subnet-select.component';
import { CoreModule } from '../../core/core.module';
/* ------------------------------------------------------------------------------------------------------------------ */

@NgModule({
    imports: [
        CommonModule,
        NgbModule,
        NgSelectModule,
        FormsModule,
        ReactiveFormsModule,
        RouterModule,
        FontAwesomeModule,
        TableModule,
        CoreModule
    ],
    declarations: [
        RenderComponent,
        RenderElementComponent,
        TextComponent,
        PasswordComponent,
        RadioComponent,
        SelectComponent,
        RefComponent,
        LocationComponent,
        CheckboxComponent,
        TextareaComponent,
        ModeErrorComponent,
        RenderErrorComponent,
        TextSimpleComponent,
        PasswordSimpleComponent,
        CheckboxSimpleComponent,
        RadioSimpleComponent,
        SelectSimpleComponent,
        RefSimpleComponent,
        LocationSimpleComponent,
        DateSimpleComponent,
        DateComponent,
        NumberComponent,
        InputAppendsComponent,
        ObjectBulkInputAppendsComponent,
        RenderFieldComponent,
        RefSectionComponent,
        FieldSectionComponent,
        MultiDataSectionComponent,
        BaseSectionComponent,
        ReferenceSectionComponent,
        SectionsFactoryComponent,
        DateFormatterPipe,
        RefSectionSimpleComponent,
        MultiDataActionsComponent,
        SubnetNetworkRangeValidatorDirective,
        SupernetNetworkRangeValidatorDirective,
        IpamSubnetSelectComponent
    ],
    exports: [
        RenderElementComponent,
        RenderComponent,
        DateFormatterPipe
    ],
    providers: [
        ...IPAM_INTERFACE_PROVIDERS
    ]
})
export class RenderModule {
}
