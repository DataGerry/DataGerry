
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
import { Routes, RouterModule } from '@angular/router';
import { SectionTemplateComponent } from './section-template.component';
import { UserSettingsResolver } from 'src/app/management/user-settings/resolvers/user-settings-resolver.service';
import { SectionTemplateAddComponent } from './layout/section-template-add/section-template-add.component';

const routes: Routes = [
    {
      path: '',
      pathMatch: 'full',
      data: {
        breadcrumb: '',
        right: 'base.framework.sectionTemplate.view'
      },
      resolve: {
        userSetting: UserSettingsResolver
      },
      component: SectionTemplateComponent
    },
    {
      path: 'add',
      data: {
        breadcrumb: 'Add',
        right: 'base.framework.sectionTemplate.add'
      },
      component: SectionTemplateAddComponent
    },
    {
      path: 'edit/:sectionTemplateID',
      data: {
        breadcrumb: 'Edit',
        right: 'base.framework.sectionTemplate.edit'
      },
      component: SectionTemplateAddComponent
    },
  ];

@NgModule({
    imports: [RouterModule.forChild(routes)],
    exports: [RouterModule]
})
export class SectionTemplateRoutingModule { }