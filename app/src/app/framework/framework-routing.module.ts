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
import { Routes, RouterModule } from '@angular/router';

import { PermissionGuard } from '../modules/auth/guards/permission.guard';

import { FrameworkComponent } from './framework.component';
/* ------------------------------------------------------------------------------------------------------------------ */

const routes: Routes = [
    {
        path: '',
        pathMatch: 'full',
        canActivate: [PermissionGuard],
        data: {
            breadcrumb: 'Overview'
        },
        component: FrameworkComponent
    },
    {
        path: 'ci-explorer',
        canActivate: [PermissionGuard],
        data: {
            breadcrumb: 'CI Explorer',
            right: 'base.framework.ciExplorer.view'
        },
        loadChildren: () => import('./launchers/ci-explorer-launch.module').then(m => m.CiExplorerLaunchModule)
    },
    {
        path: 'object',
        canActivateChild: [PermissionGuard],
        data: {
            breadcrumb: 'Object',
            right: 'base.framework.object.view'
        },
        loadChildren: () => import('./object/object.module').then(m => m.ObjectModule),
    },
    {
        path: 'type',
        canActivateChild: [PermissionGuard],
        data: {
            breadcrumb: 'Type',
            right: 'base.framework.type.view'
        },
        loadChildren: () => import('./type/type.module').then(m => m.TypeModule),
    },
    {
        path: 'relation',
        canActivateChild: [PermissionGuard],
        data: {
            breadcrumb: 'Relation',
            right: 'base.framework.relation.view'
        },
        loadChildren: () => import('./relation/relation.module').then(m => m.RelationModule),
    },
    {
        path: 'category',
        canActivateChild: [PermissionGuard],
        data: {
            breadcrumb: 'Category',
            right: 'base.framework.category.view'
        },
        loadChildren: () => import('./category/category.module').then(m => m.CategoryModule),
    },
    {
        path: 'section_templates',
        canActivateChild: [PermissionGuard],
        data: {
            breadcrumb: 'Section Templates',
            right: 'base.framework.type.view'
        },
        loadChildren: () => import('./section_templates/section-template.module').then(m => m.SectionTemplateModule),
    },
    {
        path: 'object_groups',
        canActivateChild: [PermissionGuard],
        data: {
            breadcrumb: 'Object Groups',
        },
        loadChildren: () => import('./object_groups/object-groups.module').then(m => m.ObjectGroupsModule),
    },
    {
        path: 'person-groups',
        canActivateChild: [PermissionGuard],
        data: {
            breadcrumb: 'Person Groups',
            right: 'base.framework.relation.view'
        },
        loadChildren: () => import('./person-group/person-group.module').then(m => m.PersonGroupModule),
    },

    {
        path: 'persons',
        canActivateChild: [PermissionGuard],
        data: {
            breadcrumb: 'Persons',
            right: 'base.framework.relation.view'
        },
        loadChildren: () => import('../toolbox/isms/person/person.module').then(m => m.PersonModule),
    },
];

@NgModule({
    imports: [RouterModule.forChild(routes)],
    exports: [RouterModule]
})
export class FrameworkRoutingModule { }