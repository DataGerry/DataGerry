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

import { Component, inject, Input, OnChanges, SimpleChanges, ChangeDetectorRef } from '@angular/core';

import { RenderResult } from '../../../models/cmdb-render';
import { SpecialType } from '../../../models/special-type';
import { LicenseFeature } from 'src/app/settings/license-management/models/license.model';
import { PremiumFeatureService } from 'src/app/settings/license-management/premium-feature/premium-feature.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { RACK_VIEW_RIGHT } from '../rack-overview/models/rack-overview.types';

/** The tabs the footer card can show; the rack one is only offered on rack objects. */
type ObjectFooterTab =
  | 'risk-assessments'
  | 'references'
  | 'logs'
  | 'relation-logs'
  | 'summaries'
  | 'metadata'
  | 'qr'
  | 'rack-view';

@Component({
  selector: 'cmdb-object-footer',
  templateUrl: './object-footer.component.html',
  styleUrls: ['./object-footer.component.scss'],
  standalone: false
})
export class ObjectFooterComponent implements OnChanges {

  public objectID: number;
  public readonly LicenseFeature = LicenseFeature;

  public activeTab: ObjectFooterTab = 'risk-assessments';

  /** The rack drawing is only built once its tab has been on screen. */
  public rackTabVisited = false;

  /** A tab the user picked outlives the object; the untouched default gives way to the rack. */
  private tabPickedByUser = false;

  private rr: RenderResult;

  private readonly premiumFeatureService = inject(PremiumFeatureService);
  private readonly permissionService = inject(PermissionService);
  private readonly canViewRack = this.permissionService.hasRight(RACK_VIEW_RIGHT)
    || this.permissionService.hasExtendedRight(RACK_VIEW_RIGHT);

  /** Risk Assessments belong to ISMS; locked editions see a "Pro" placeholder instead of the list. */
  public get ismsAvailable(): boolean {
    return this.premiumFeatureService.isAvailable(LicenseFeature.Isms);
  }

  /** The tab only frames the rack drawing, so it needs the same view right. */
  public get showRackView(): boolean {
    return this.rr?.object_information?.special_type === SpecialType.RACK && this.canViewRack;
  }

  @Input('renderResult')
  public set renderResult(rr) {
    if (rr !== undefined) {
      this.rr = rr;
      this.objectID = rr.object_information.object_id;
    }
  }

  public get renderResult() {
    return this.rr;
  }

  private readonly changesRef = inject(ChangeDetectorRef);

  public ngOnChanges(changes: SimpleChanges): void {
    this.objectID = this.renderResult.object_information.object_id;
    this.resolveActiveTab();

    // Another object means another drawing, so it is only kept while its tab is the one on screen.
    this.rackTabVisited = this.activeTab === 'rack-view';

    this.changesRef.markForCheck();
  }

  /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

  public selectTab(tab: ObjectFooterTab): void {
    this.activeTab = tab;
    this.tabPickedByUser = true;
    this.rackTabVisited = this.rackTabVisited || tab === 'rack-view';
  }

  /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  /** A rack leads with its drawing; opening a mounted object leaves both the rack and its tab behind. */
  private resolveActiveTab(): void {
    if (this.showRackView) {
      if (!this.tabPickedByUser) {
        this.activeTab = 'rack-view';
      }

      return;
    }

    if (this.activeTab === 'rack-view') {
      this.activeTab = 'risk-assessments';
    }
  }
}
