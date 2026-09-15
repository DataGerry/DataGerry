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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Injectable } from '@angular/core';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { Router } from '@angular/router';
import { ISMSService } from './isms.service';
import { CoreWarningModalComponent } from 'src/app/core/components/dialog/core-warning-modal/core-warning-modal.component';
import { IsmsConfigValidation } from '../models/isms-config-validation.model';
import { Observable, of } from 'rxjs';
import {  map, switchMap } from 'rxjs/operators';
import { Location } from '@angular/common';

@Injectable({
  providedIn: 'root'
})
export class IsmsValidationService {
  constructor(
    private ismsService: ISMSService,
    private modalService: NgbModal,
    private router: Router,
    private location: Location
  ) {}

  /**
   * Returns true if config is valid, otherwise opens a modal and navigates
   */
  checkAndHandleInvalidConfig(): Observable<boolean> {
    return this.ismsService.getIsmsValidationStatus().pipe(
      switchMap((status: IsmsConfigValidation) => {
        const isValid =
          status.risk_classes &&
          status.likelihoods &&
          status.impacts &&
          status.impact_categories &&
          status.risk_matrix;

        if (isValid) {
          return of(true);
        }

        const modalRef = this.modalService.open(CoreWarningModalComponent, {
          centered: true,
          windowClass: 'dg-modal-window',
          backdropClass: 'dg-modal-window-backdrop'
        });
        modalRef.componentInstance.title = 'ISMS Configuration Required';
        modalRef.componentInstance.message = 'Your ISMS configuration is incomplete. Please configure your settings before continuing.';
        modalRef.componentInstance.confirmLabel = 'Go to ISMS Settings';
        modalRef.componentInstance.cancelLabel = 'Cancel';
        modalRef.componentInstance.route = '/isms/configure';

        // Listen to modal result
        return modalRef.result.then(
          () => false, // when confirmed
          () => {
            this.location.back(); // go back on cancel
            return false;
          }
        );
      })
    );
  }


    /**
   * Returns true if config is valid.
   * This version does not show a modal.
   */
    checkConfigSilently(): Observable<boolean> {
      return this.ismsService.getIsmsValidationStatus().pipe(
        map((status: IsmsConfigValidation) =>
          status.risk_classes &&
          status.likelihoods &&
          status.impacts &&
          status.impact_categories &&
          status.risk_matrix
        )
      );
    }
  
}
