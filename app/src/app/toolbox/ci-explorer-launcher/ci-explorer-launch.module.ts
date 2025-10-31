import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { CommonModule } from '@angular/common';
import { CoreModule } from 'src/app/core/core.module';

const routes: Routes = [ { path: '', loadComponent: () => import('./ci-explorer-launch.page').then(m => m.CiExplorerLaunchPage) } ];

@NgModule({
  imports: [CommonModule, CoreModule, RouterModule.forChild(routes)],
  declarations: []
})
export class CiExplorerLaunchModule {}
