import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { ObjectGroupsListComponent } from './object-groups-list.component';
import { ObjectGroupsAddComponent } from './add/object-groups-add.component';

const routes: Routes = [
  {
    path: '',
    component: ObjectGroupsListComponent,
    data: { right: 'base.framework.objectGroup.view' }
  },
  {
    path: 'add',
    component: ObjectGroupsAddComponent,
    data: { right: 'base.framework.objectGroup.add' }
  },
  {
    path: 'edit/:id',
    component: ObjectGroupsAddComponent,
    data: { right: 'base.framework.objectGroup.edit' }
  },
  {
    path: 'view/:id',
    component: ObjectGroupsAddComponent,
    // Read-only flag comes from the route, not from the navigation state
    data: { right: 'base.framework.objectGroup.view', isViewMode: true }
  }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class ObjectGroupsRoutingModule {}
