import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { RouterModule, Routes } from '@angular/router';

import { TableModule } from "../layout/table/table.module";
import { WebhookFormComponent } from './components/webhook-form/webhook-form.component';
import { WebhookOverviewComponent } from './components/webhook-overview/webhook-overview.component';
import { WebhookLogViewerComponent } from './components/webhook-log-viewer/webhook-log-viewer.component';
import { NgSelectModule } from '@ng-select/ng-select';
import { UserSettingsResolver } from '../management/user-settings/resolvers/user-settings-resolver.service';
import { AuthModule } from '../modules/auth/auth.module';
import { CoreModule } from '../core/core.module';

const routes: Routes = [
    {
      path: '',
      data: {
        breadcrumb: 'Webhooks',
        right: 'base.framework.webhook.view'
      },
      resolve: {
        userSetting: UserSettingsResolver
      },
      children: [
        {
          path: '',
          component: WebhookOverviewComponent
        },
        {
          path: 'create',
          data: {
            breadcrumb: 'Create WebHook',
            right: 'base.framework.webhook.add'
          },
          component: WebhookFormComponent
        },
        {
          path: 'edit/:id',
          data: {
            breadcrumb: 'Edit WebHook',
            right: 'base.framework.webhook.edit'
          },
          component: WebhookFormComponent
        },
        {
          path: 'logs',
          data: {
            breadcrumb: 'WebHook Logs',
            right: 'base.framework.webhook.view'
          },
          component: WebhookLogViewerComponent
        }
      ]
    }
  ];
  

@NgModule({
    declarations: [
        WebhookOverviewComponent,
        WebhookFormComponent,
        WebhookLogViewerComponent,
    ],
    imports: [
        CommonModule,
        FormsModule,
        ReactiveFormsModule,
        RouterModule.forChild(routes),
        TableModule,
        NgSelectModule,
        AuthModule,
        // LayoutModule
        CoreModule
    ],
    providers: [],
})
export class WebhookModule { }
