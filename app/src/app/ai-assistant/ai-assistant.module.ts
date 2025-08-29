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
import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule } from '@angular/forms';
import { NgbModule } from '@ng-bootstrap/ng-bootstrap';

import { AiAssistantRoutingModule } from './ai-assistant-routing.module';

import { AiPromptPageComponent } from './components/ai-prompt-page/ai-prompt-page.component';
import { AiSectionSelectorComponent } from './components/ai-section-selector/ai-section-selector.component';
import { CoreModule } from '../core/core.module';

@NgModule({
  declarations: [
    AiPromptPageComponent,
    AiSectionSelectorComponent
  ],
  imports: [
    CommonModule,
    ReactiveFormsModule,
    NgbModule,
    CoreModule,
    AiAssistantRoutingModule
  ]
})
export class AiAssistantModule {}
