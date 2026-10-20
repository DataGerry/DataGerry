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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
// import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
// import { ISMSService } from '../services/isms.service';
// import { IsmsConfigValidation } from '../models/isms-config-validation.model';
// import { LoaderService } from 'src/app/core/services/loader.service';
// import { finalize } from 'rxjs';
// import { ToastService } from 'src/app/layout/toast/toast.service';

import { Component, inject, OnInit, ChangeDetectorRef } from "@angular/core";
import { LoaderService } from "src/app/core/services/loader.service";
import { PermissionService } from "src/app/modules/auth/services/permission.service";
import { ToastService } from "src/app/layout/toast/toast.service";
import { IsmsConfigValidation } from "../models/isms-config-validation.model";
import { IsmsOverviewCard } from "../models/isms-overview-card.model";
import { ISMSService } from "../services/isms.service";
import { finalize } from "rxjs";

@Component({
  selector: 'app-isms-overview',
  templateUrl: './overview.component.html',
  styleUrls: ['./overview.component.scss'],
  standalone: false
})
export class OverviewComponent implements OnInit {

  private readonly ismsService = inject(ISMSService);
  private readonly cdRef = inject(ChangeDetectorRef);
  private readonly loaderService = inject(LoaderService);
  private readonly toastService = inject(ToastService);
  private readonly permissionService = inject(PermissionService);

  public validationStatus: boolean = false;
  public isLoading$ = this.loaderService.isLoading$;


  public cards: IsmsOverviewCard[] = [
    {
      title: 'Configure ISMS Settings',
      icon: 'fas fa-cogs',
      link: '/isms/configure',
      validationStatus: false
    },
    {
      title: 'Risks',
      icon: 'fas fa-exclamation-triangle',
      link: '/isms/risks',
      right: 'base.isms.risk.view'
    },
    {
      title: 'Controls',
      icon: 'fas fa-shield-alt',
      link: '/isms/control-measures',
      right: 'base.isms.controlMeasure.view'
    },
    {
      title: 'Threats',
      icon: 'fas fa-bolt',
      link: '/isms/threats',
      right: 'base.isms.threat.view'
    },
    {
      title: 'Vulnerabilities',
      icon: 'fas fa-bug',
      link: '/isms/vulnerabilities',
      right: 'base.isms.vulnerability.view'
    },
    {
      title: 'Reports',
      icon: 'fas fa-file-alt',
      link: '/isms/reports',
      right: 'base.isms.report.view'
    }
  ];

  // Mirrors the route guards so a card is only shown when its target would actually open.
  public visibleCards: IsmsOverviewCard[] = this.cards.filter(card => this.canOpen(card));


  ngOnInit(): void {
    this.loaderService.show(); // Show loader
    this.ismsService.getIsmsValidationStatus().pipe(finalize(() => {
      this.loaderService.hide();
    })).subscribe({
      next: (status: IsmsConfigValidation) => {
        const isValid =
          status.risk_classes &&
          status.likelihoods &&
          status.impacts &&
          status.impact_categories &&
          status.risk_matrix;

        this.cards.forEach(card => {
          if (card.hasOwnProperty('validationStatus')) {
            card.validationStatus = isValid;
          }
        });

        // Trigger change detection
        this.cdRef.detectChanges();
      },
      error: (err) => {
        this.toastService.error(err?.error?.message)
      }
    });
  }


  private canOpen(card: IsmsOverviewCard): boolean {
    if (!card.right) {
      return true;
    }

    return this.permissionService.hasRight(card.right) || this.permissionService.hasExtendedRight(card.right);
  }

}
