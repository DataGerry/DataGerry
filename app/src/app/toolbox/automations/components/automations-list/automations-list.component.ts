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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { Router } from '@angular/router';

import { AutomationsService } from '../../services/automations.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { DeleteModalService } from 'src/app/core/services/delete-modal.service';
import { ConnectorsService } from 'src/app/toolbox/connectors/services/connectors.service';
import { finalize } from 'rxjs';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { CronExpressionModalComponent } from '../cron-expression-modal/cron-expression-modal.component';
import { environment } from 'src/environments/environment';

@Component({
  selector: 'app-automations-list',
  templateUrl: './automations-list.component.html',
  styleUrls: ['./automations-list.component.scss'],
  standalone: false
})
export class AutomationsListComponent implements OnInit {
  // Table column templates
  @ViewChild('actionsTemplate', { static: true }) actionsTemplate: TemplateRef<any>;
  @ViewChild('directionTemplate', { static: true }) directionTemplate: TemplateRef<any>;
  @ViewChild('statusTemplate', { static: true }) statusTemplate: TemplateRef<any>;
  @ViewChild('lastSuccessTemplate', { static: true }) lastSuccessTemplate: TemplateRef<any>;
  @ViewChild('lastFailTemplate', { static: true }) lastFailTemplate: TemplateRef<any>;
  @ViewChild('lastDurationTemplate', { static: true }) lastDurationTemplate: TemplateRef<any>;
  @ViewChild('logsTemplate', { static: true }) logsTemplate: TemplateRef<any>;

  public automations: any[] = [];
  public totalAutomations: number = 0;
  public loading = false;
  public page = 1;
  public limit = 0;
  public columns: Array<any>;
  public isLoading$ = this.loaderService.isLoading$;
  public isExecuting: string | null = null;
  public logToggleLoading: Record<string, boolean> = {};
  public isCloudMode = environment.cloudMode;

  constructor(
    private svc: ConnectorsService,
    private automationsService: AutomationsService,
    private router: Router,
    private toast: ToastService,
    private loaderService: LoaderService,
    private deleteModalService: DeleteModalService,
    private modalService: NgbModal
  ) { }

  ngOnInit(): void {
    this.columns = [
      {
        display: 'Name',
        name: 'name',
        data: 'connection.title',
        sortable: false,
        style: { width: '200px' }
      },
      {
        display: 'Direction',
        name: 'direction',
        template: this.directionTemplate,
        sortable: false,
        style: { width: '100px', 'text-align': 'center' }
      },
      {
        display: 'Cron',
        name: 'cron',
        data: 'cronExp',
        sortable: false,
        style: { width: '150px' }
      },
      {
        display: 'Last Success',
        name: 'lastSuccess',
        template: this.lastSuccessTemplate,
        sortable: false,
        style: { width: '150px' }
      },
      {
        display: 'Last Fail',
        name: 'lastFail',
        template: this.lastFailTemplate,
        sortable: false,
        style: { width: '150px' }
      },
      {
        display: 'Last Duration',
        name: 'lastDuration',
        template: this.lastDurationTemplate,
        sortable: false,
        style: { width: '120px' }
      },
      {
        display: 'Logs',
        name: 'logs',
        template: this.logsTemplate,
        sortable: false,
        style: { width: '80px', 'text-align': 'center' }
      },
      {
        display: 'Status',
        name: 'status',
        template: this.statusTemplate,
        sortable: false,
        style: { width: '100px', 'text-align': 'center' }
      },
      {
        display: 'Actions',
        name: 'actions',
        template: this.actionsTemplate,
        sortable: false,
        style: { width: '140px', 'text-align': 'center' }
      }
    ];

    this.loadAutomations();
  }


  loadAutomations(): void {
    this.loading = true;
    this.loaderService.show();

    this.automationsService?.getAutomations()?.subscribe({
      next: (automations) => {
        // Map automations to add direction information
        const list = Array.isArray(automations) ? automations : [];

        this.automations = list?.map(automation => ({
          ...automation,
          direction: this.getDirection(automation)
        }));
      
        this.totalAutomations = list?.length;
        this.loading = false;
        this.loaderService.hide();
      },
      error: (error) => {
        this.toast.error(error?.error?.message);
        this.loading = false;
        this.loaderService.hide();
      }
    });
  }

    configInternal(): void {
      this.loaderService.show();
      this.svc.checkConnectorExists('DataGerryInternal')
        .pipe(finalize(() => this.loaderService.hide()))
        .subscribe({
          next: (exists: boolean) => {
            // Redirect to internal route without resolver
            this.router.navigate(['automations/connectors/internal'], {
              state: { 
                connectorExists: exists,
                connector: {
                  title: 'DataGerryInternal',
                  description: 'Internal DATAGerry connector for automations',
          invoker: { name: environment.cloudMode ? 'DataGerryCloud' : 'DataGerry' },
                  sslCert: false,
                  timeout: 1000
                }
              }
            });
          },
          error: (err) => {
            this.toast.error(err?.error?.message);
          }
        });
    }


  private getDirection(automation: any): string {
    const fromConnector = automation?.connection?.fromConnector;
    const toConnector = automation?.connection?.toConnector;

    if (fromConnector?.title === 'DataGerryInternal' && toConnector?.title !== 'DataGerryInternal') {
      return 'outgoing';
    } else if (toConnector?.title === 'DataGerryInternal' && fromConnector?.title !== 'DataGerryInternal') {
      return 'incoming';
    } else if (fromConnector?.title === 'DataGerryInternal' && toConnector?.title === 'DataGerryInternal') {
      return 'internal';
    }
  }


  editAutomation(automation: any): void {
    const connectionId = automation.connection?.connectionId;
    
    if (!connectionId) {
      return;
    }

    // Show loading state
    this.loaderService.show();

    this.automationsService?.getConnection(connectionId)?.subscribe({
      next: (connectionData) => {
        // Create updated automation with full connection data
        const updatedAutomation = {
          ...automation,
          connection: connectionData
        };

        this.router.navigate(['/automations/edit', automation.schedulerId], {
          state: { automation: updatedAutomation }
        });
        this.loaderService.hide();
      },
      error: (err) => {
        this.toast.error(err?.error?.message);
        this.loaderService.hide();
      }
    });
  }


  setCron(automation: any): void {
    const modalRef = this.modalService.open(CronExpressionModalComponent, { size: 'lg' });
    modalRef.componentInstance.currentCron = automation?.cronExp || automation?.scheduler?.cronExp || '';
    modalRef.componentInstance.automationName = automation?.connection?.title || automation?.scheduler?.title || automation?.name || '';

    modalRef.result
      .then((cronExp: string) => {
        if (!cronExp) {
          return;
        }
        this.updateCronExp(automation, cronExp);
      })
      .catch(() => {});
  }


  private updateCronExp(automation: any, cronExp: string): void {
    const schedulerId = automation?.schedulerId;
    const connectionId = automation?.connection?.connectionId;
    if (!schedulerId) {
      return;
    }
    if (!connectionId) {
      return;
    }

    this.loaderService.show();

    const schedulerPayload = {
      schedulerId,
      connectionId,
      title: automation?.title || automation?.scheduler?.title || automation?.name,
      status: automation.status,
      cronExp,
      debugMode: automation?.debugMode,
      notificationResources: []
    };

    this.automationsService.updateScheduler(schedulerId, schedulerPayload)
      .pipe(finalize(() => this.loaderService.hide()))
      .subscribe({
        next: () => {
          this.toast.success('Cron job updated successfully');
          this.loadAutomations();
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }

  toggleDebugMode(automation: any, event: Event): void {
    event?.stopPropagation();
    const schedulerId = automation?.schedulerId;
    const connectionId = automation?.connection?.connectionId;
    if (!schedulerId || !connectionId) {
      return;
    }

    const enabled = !!(event?.target as HTMLInputElement)?.checked;
    const schedulerPayload = {
      schedulerId,
      connectionId,
      title: automation?.title,
      status: automation.status,
      cronExp: automation?.cronExp,
      debugMode: enabled,
      notificationResources: []
    };

    this.logToggleLoading[schedulerId] = true;

    this.automationsService.updateScheduler(schedulerId, schedulerPayload)
      .pipe(finalize(() => {
        this.logToggleLoading[schedulerId] = false;
      }))
      .subscribe({
        next: () => {
          automation.debugMode = enabled;
          this.toast.success(enabled ? 'Logs enabled' : 'Logs disabled');
        },
        error: (err) => {
          this.toast.error(err?.error?.message || 'Failed to update logs');
          const input = event?.target as HTMLInputElement;
          if (input) {
            input.checked = !enabled;
          }
        }
      });
  }


    delete(automation: any): void {
      const schedulerId = automation.schedulerId;

      this.deleteModalService.confirmDelete({
        title: `Delete Automation:`,
        itemType: 'Automation',
        itemName: automation.connection?.title || automation.scheduler?.title || automation.name,
        onConfirm: () => {
          this.automationsService?.deleteAutomation(schedulerId)?.subscribe({
            next: () => { this.toast.success('Automation deleted successfully'); this.loadAutomations(); },
            error: () => this.toast.error('Delete failed')
          });
        }
      });
    }



  executeScheduler(schedulerId: any): void {
    this.isExecuting = schedulerId;

    this.automationsService?.executeScheduler(schedulerId)?.subscribe({
      next: () => {
        this.toast.success('Automation execution started');
        this.isExecuting = null;
        // reload automations to update last execution times
        this.loadAutomations();
      },
      error: (err) => {
        this.toast.error(err?.error?.message);
        this.isExecuting = null;
      }
    });
  }


  onPageChange(newPage: number): void {
    this.page = newPage;
    this.loadAutomations();
  }


  onPageSizeChange(newLimit: number): void {
    this.limit = newLimit;
    this.page = 1;
    this.loadAutomations();
  }


  // Helper method to format Unix timestamp to readable date
  private formatDate(timestamp: number): string {
    if (!timestamp) return '-';
    return new Date(timestamp).toLocaleString();
  }


  // Helper method to extract the value after dash from taId
  private getTaIdNumber(taId: string): string {
    if (!taId) return '';
    const parts = taId.split('-');
    return parts.length > 1 ? `#${parts[1]}` : '';
  }


  // Helper method to get last success display data
  getLastSuccessDisplay(automation: any): { date: string, taId: string } {
    const success = automation?.lastExecution?.success;
    if (!success) {
      return { date: '-', taId: '' };
    }
    return {
      date: this.formatDate(success.startTime),
      taId: this.getTaIdNumber(success.taId)
    };
  }


  // Helper method to get last fail display data
  getLastFailDisplay(automation: any): { date: string, taId: string } {
    const fail = automation?.lastExecution?.fail;
    if (!fail) {
      return { date: '-', taId: '' };
    }
    return {
      date: this.formatDate(fail.startTime),
      taId: this.getTaIdNumber(fail.taId)
    };
  }


  // Helper method to get last duration
  getLastDuration(automation: any): string {
    const success = automation?.lastExecution?.success;
    const fail = automation?.lastExecution?.fail;

    if (success?.duration) {
      return `${success.duration}ms`;
    } else if (fail?.duration) {
      return `${fail.duration}ms`;
    }
    return 'N/A';
  }

  hasLastSuccess(automation: any): boolean {
    return !!automation?.lastExecution?.success;
  }

  hasLastFail(automation: any): boolean {
    return !!automation?.lastExecution?.fail;
  }

}
