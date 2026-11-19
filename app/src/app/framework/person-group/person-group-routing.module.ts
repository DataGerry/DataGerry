import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';

import { PersonGroupListComponent } from './person-group-list/person-group-list.component';
import { PersonGroupAddEditComponent } from './person-group-add/person-group-add-edit.component';

const routes: Routes = [

  {
    path: '', component: PersonGroupListComponent,
    data: {
      breadcrumb: 'New',
      right: 'base.framework.object.view'
    },
  },
  {
    path: 'add', component: PersonGroupAddEditComponent,
    data: {
      breadcrumb: 'Add',
      right: 'base.framework.object.add'
    },
  },
  {
    path: 'edit', component: PersonGroupAddEditComponent,
    data: {
      breadcrumb: 'Edit',
      right: 'base.framework.object.edit'
    },
  }
];

@NgModule({
  imports: [RouterModule.forChild(routes)  ],
  exports: [RouterModule]
})
export class PersonGroupRoutingModule { }
