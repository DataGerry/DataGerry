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

import { Injectable } from '@angular/core';
import { Router } from '@angular/router';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { finalize } from 'rxjs/operators';

import { ConnectorsService } from './connectors.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { CoreConfirmationModalComponent } from 'src/app/core/components/dialog/confirmation/core-confirmation-modal.component';
import { environment } from 'src/environments/environment';

export interface InternalConnectorCheckOptions {
  onExists: () => void;
  redirectRoute: any[];
  description: string;
  cancelRoute?: any[];
  errorRoute?: any[];
}

@Injectable({
  providedIn: 'root'
})
export class InternalConnectorHelperService {
  constructor(
    private connectorsService: ConnectorsService,
    private loaderService: LoaderService,
    private toast: ToastService,
    private modalService: NgbModal,
    private router: Router
  ) {}

  checkInternalConnector(options: InternalConnectorCheckOptions): void {
    this.loaderService.show();

    this.connectorsService.checkConnectorExists('DataGerryInternal')
      .pipe(finalize(() => this.loaderService.hide()))
      .subscribe({
        next: (exists) => {
          if (exists) {
            options.onExists();
          } else {
            this.showInternalConnectorModal(options);
          }
        },
        error: (error) => {
          this.toast.error(error?.error?.message);
          if (options.errorRoute) {
            this.router.navigate(options.errorRoute);
          }
        }
      });
  }

  private showInternalConnectorModal(options: InternalConnectorCheckOptions): void {
    const modalRef = this.modalService.open(CoreConfirmationModalComponent, {
      centered: true,
      backdrop: 'static'
    });

    modalRef.componentInstance.title = 'DataGerry API Credentials Required';
    modalRef.componentInstance.message = 'DataGerry API Credentials are not saved. Do you want to save it now?';
    modalRef.componentInstance.confirmButtonText = 'Save Now';
    modalRef.componentInstance.cancelButtonText = 'Cancel';
    modalRef.componentInstance.confirmButtonClass = 'btn-primary';

    modalRef.result.then(
      (result) => {
        if (result === 'confirmed') {
          this.redirectToInternalConnectorSetupFromOptions(options);
        }
      },
      () => {
        if (options.cancelRoute) {
          this.router.navigate(options.cancelRoute);
        }
      }
    );
  }

  redirectToInternalConnectorSetup(redirectRoute: any[], description: string): void {
    this.router.navigate(redirectRoute, {
      state: {
        connectorExists: false,
        connector: {
          title: 'DataGerryInternal',
          description,
          invoker: { name: environment.cloudMode ? 'DataGerryCloud' : 'DataGerry' },
          sslCert: false,
          timeout: 1000
        }
      }
    });
  }

  private redirectToInternalConnectorSetupFromOptions(options: InternalConnectorCheckOptions): void {
    this.redirectToInternalConnectorSetup(options.redirectRoute, options.description);
  }
}
