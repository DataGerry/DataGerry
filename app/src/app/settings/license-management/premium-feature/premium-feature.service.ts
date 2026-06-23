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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { inject, Injectable } from '@angular/core';
import { Router } from '@angular/router';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { Observable, of } from 'rxjs';
import { catchError, finalize, map, tap } from 'rxjs/operators';

import { environment } from 'src/environments/environment';
import { LoaderService } from 'src/app/core/services/loader.service';
import {
  PREMIUM_FEATURE_MODAL_RESULT,
  PremiumFeatureModalComponent
} from 'src/app/core/components/dialog/premium-feature-modal/premium-feature-modal.component';

import { LicenseFeature } from '../models/license.model';
import { LicenseService } from '../services/license.service';
import { PREMIUM_FEATURE_CONTENT } from './premium-feature.config';

/** Route the upgrade call-to-action sends the user to. */
const LICENSE_MANAGEMENT_ROUTE = '/settings/license';

/**
 * Coordinates the premium-feature gate: resolves whether the current edition unlocks a feature and,
 * when it does not, presents the upgrade modal and routes the user to license management.
 *
 * All licensing logic lives here; the modal component stays purely presentational.
 */
@Injectable({ providedIn: 'root' })
export class PremiumFeatureService {

  private readonly modalService = inject(NgbModal);
  private readonly router = inject(Router);
  private readonly licenseService = inject(LicenseService);
  private readonly loaderService = inject(LoaderService);

  /* --------------------------------------------------- FUNCTIONS --------------------------------------------------- */

  /**
   * Gate used by route guards: emits `true` when the feature is unlocked, otherwise opens the upgrade
   * modal and emits `false` so navigation is cancelled.
   */
  ensureAccess(feature: LicenseFeature): Observable<boolean> {
    return this.isFeatureUnlocked(feature).pipe(
      tap((unlocked) => {
        if (!unlocked) {
          this.openUpgradeModal(feature);
        }
      })
    );
  }

  /**
   * Resolves whether the active edition entitles the given feature.
   *
   * Cloud deployments are always entitled (and expose no license endpoint), so they short-circuit to
   * `true`. On-premise installs are decided by the verified license; a failed lookup degrades safely
   * to "locked".
   */
  isFeatureUnlocked(feature: LicenseFeature): Observable<boolean> {
    if (environment.cloudMode) {
      return of(true);
    }

    this.loaderService.show();

    return this.licenseService.getCurrentLicense().pipe(
      map((license) => license.is_active && license.entitlement.features.includes(feature)),
      catchError(() => of(false)),
      finalize(() => this.loaderService.hide())
    );
  }

  /**
   * Resolves which of the supplied premium features are currently LOCKED for the active edition.
   *
   * Intended for passive UI hints (e.g. premium badges): Cloud deployments unlock everything, so the
   * result is always empty; on-premise installs derive the locked set from the verified license in a
   * single lookup, and a failed lookup degrades safely to "all locked". Unlike `isFeatureUnlocked`,
   * this does not toggle the global loader.
   */
  getLockedFeatures(features: readonly LicenseFeature[]): Observable<Set<LicenseFeature>> {
    if (environment.cloudMode) {
      return of(new Set<LicenseFeature>());
    }

    return this.licenseService.getCurrentLicense().pipe(
      map((license) => {
        const unlocked = license.is_active ? license.entitlement.features : [];
        return new Set(features.filter((feature) => !unlocked.includes(feature)));
      }),
      catchError(() => of(new Set(features)))
    );
  }

  /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  /** Opens the showcase modal for a feature and routes to license management on confirmation. */
  private openUpgradeModal(feature: LicenseFeature): void {
    const content = PREMIUM_FEATURE_CONTENT[feature];

    if (!content) {
      this.router.navigate([LICENSE_MANAGEMENT_ROUTE]);
      return;
    }

    // The blocked navigation has not been applied yet (deferred URL update), so this is still the
    // page the user came from — where "Maybe later" should return them.
    const returnUrl = this.router.url;

    const modalRef = this.modalService.open(PremiumFeatureModalComponent, {
      size: 'lg',
      centered: true,
      windowClass: 'premium-feature-window',
      modalDialogClass: 'premium-feature-dialog',
      ariaLabelledBy: 'premium-feature-title',
      ariaDescribedBy: 'premium-feature-description'
    });

    const instance = modalRef.componentInstance as PremiumFeatureModalComponent;
    instance.title = content.title;
    instance.subtitle = content.subtitle;
    instance.description = content.description;
    instance.icon = content.icon;
    instance.benefits = content.benefits;

    modalRef.result.then(
      (result) => {
        if (result === PREMIUM_FEATURE_MODAL_RESULT.upgrade) {
          this.router.navigate([LICENSE_MANAGEMENT_ROUTE]);
        } else {
          this.returnToSource(returnUrl);
        }
      },
      () => this.returnToSource(returnUrl)
    );
  }

  /**
   * Sends the user back to the page they came from after declining the upgrade ("Maybe later",
   * the close button or the backdrop). For a blocked menu click this resolves to the current page
   * (a no-op), and it rescues users who deep-linked or refreshed straight onto the gated route.
   */
  private returnToSource(returnUrl: string): void {
    this.router.navigateByUrl(returnUrl || '/');
  }
}
