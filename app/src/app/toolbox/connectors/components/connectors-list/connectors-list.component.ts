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

import { Component, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { Router } from '@angular/router';
import { ConnectorsService } from '../../services/connectors.service';
import { Connector } from '../../models/connector.model';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { DeleteModalService } from 'src/app/core/services/delete-modal.service';
import { finalize } from 'rxjs';

@Component({
  selector: 'app-connectors-list',
  templateUrl: './connectors-list.component.html',
  styleUrls: ['./connectors-list.component.scss'],
  standalone: false
})
export class ConnectorsListComponent implements OnInit {
  @ViewChild('actionsTemplate', { static: true }) actionsTemplate: TemplateRef<any>;

  rows: Connector[] = [];
  loading = false;
  columns: any[];
  totalConnectors = 0;

  constructor(
    private svc: ConnectorsService,
    private router: Router,
    private toast: ToastService,
    private loaderService: LoaderService,
    private deleteModalService: DeleteModalService
  ) { }

  ngOnInit(): void {
    this.columns = [
      { display: 'Public ID', name: 'connectorId', data: 'connectorId', sortable: false, style: { width: '120px', 'text-align': 'center' } },
      { display: 'Label', name: 'title', data: 'title', sortable: false , style: {'text-align': 'center' } },
      { display: 'Actions', name: 'actions', template: this.actionsTemplate, sortable: false, style: { width: '100px', 'text-align': 'center' } }
    ];
    this.loadConnectors();
  }

  loadConnectors(): void {
    this.loaderService.show();
    this.svc.getConnectors().pipe(finalize(() => this.loaderService.hide())).subscribe({
      next: (res) => { this.rows = res ?? []; 
        this.totalConnectors = this.rows.length;
      },
      error: (err) => {
        this.loading = false;
        this.toast.error(err?.error?.message);
      }
    });
  }

  add(): void { this.router.navigate(['/connectors/add']); }
  edit(row: Connector): void { 
    this.router.navigate(['/connectors/edit', row.connectorId], {
      state: { connector: row }
    });
  }

  configInternal(): void {
    this.loaderService.show();
    this.svc.checkConnectorExists('DataGerryInternal')
      .pipe(finalize(() => this.loaderService.hide()))
      .subscribe({
        next: (exists: boolean) => {
          if (exists) {
            // Navigate to internal configuration with pre-filled data
            this.router.navigate(['/connectors/internal'], {
              state: { 
                connector: {
                  title: 'DataGerryInternal',
                  description: 'Internal DataGerry connector for data query operations',
                  invoker: { name: 'datagerry' }
                }
              }
            });
          } else {
            this.toast.error('Internal connector "datagerry" does not exist');
          }
        },
        error: (err) => {
          this.toast.error(err?.error?.message || 'Failed to check connector existence');
        }
      });
  }

  delete(row: Connector): void {
    this.deleteModalService.confirmDelete({
      title: `Delete Connector: ${row.title}`,
      itemType: 'Connector',
      itemName: row.title,
      onConfirm: () => {
        this.svc.deleteConnector(row.connectorId!).subscribe({
          next: () => { this.toast.success('Connector deleted'); this.loadConnectors(); },
          error: () => this.toast.error('Delete failed')
        });
      }
    });
  }

}
