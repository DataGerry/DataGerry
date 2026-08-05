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
import { inject, Injectable, signal } from '@angular/core';
import { toObservable } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { Observable, of } from 'rxjs';
import { catchError, distinctUntilChanged, map, shareReplay, switchMap, take, tap } from 'rxjs/operators';

import { environment } from 'src/environments/environment';
import {
  PREMIUM_FEATURE_MODAL_RESULT,
  PremiumFeatureModalComponent
} from 'src/app/core/components/dialog/premium-feature-modal/premium-feature-modal.component';

import { COMMUNITY_TIER, CurrentLicense, LicenseFeature } from '../models/license.model';
import { remainingDays } from '../utils/license.util';
import { LicenseService } from '../services/license.service';
import { PREMIUM_FEATURE_CONTENT } from './premium-feature.config';

/** Route the upgrade call-to-action sends the user to. */
const LICENSE_MANAGEMENT_ROUTE = '/settings/license';

/**
 * Single source of truth for premium-feature gating.
 *
 * The active license is fetched once and cached in a signal; every gate in the app (route guards,
 * toolbox badges, the gating directives) reads from that cache instead of hitting the endpoint
 * itself. The modal stays purely presentational and all licensing logic lives here.
 */
@Injectable({ providedIn: 'root' })
export class PremiumFeatureService {

  private readonly modalService = inject(NgbModal);
  private readonly router = inject(Router);
  private readonly licenseService = inject(LicenseService);

  /**
   * Cached license. `undefined` means "not hydrated yet", `null` means "hydrated but no valid
   * license" (Community); an object is the verified license.
   */
  private readonly license = signal<CurrentLicense | null | undefined>(undefined);

  /** RxJS view of the cache for the reactive consumers (guards, directives, badges). */
  private readonly license$ = toObservable(this.license);

  /** Shared in-flight hydration request, so concurrent first-time callers trigger a single fetch. */
  private hydration$?: Observable<CurrentLicense | null>;

  /* --------------------------------------------------- FUNCTIONS --------------------------------------------------- */

  /**
   * Synchronous entitlement snapshot for passive UI (badges, structural gates, the type form).
   *
   * Cloud is always entitled. On-premise it fails closed while the license is still unknown and
   * treats an inactive, expired or unlicensed state as locked. Expiry is evaluated locally against
   * the cached `endDate`, so a license lapsing mid-session is caught without another network call.
   */
  isAvailable(feature: LicenseFeature): boolean {
    if (environment.cloudMode) {
      return true;
    }

    const license = this.license();
    if (!license || !license.is_active) {
      return false;
    }

    const days = remainingDays(license.entitlement.endDate, Date.now());
    if (days !== null && days < 0) {
      return false;
    }

    return license.entitlement.features.includes(feature);
  }

  /**
   * Reactive entitlement stream for directives and badges: waits for the first hydration, then
   * re-emits whenever the cached license changes (import/removal). Fails closed until known.
   */
  isAvailable$(feature: LicenseFeature): Observable<boolean> {
    if (environment.cloudMode) {
      return of(true);
    }

    return this.ensureHydrated().pipe(
      switchMap(() => this.license$),
      map(() => this.isAvailable(feature)),
      distinctUntilChanged()
    );
  }

  /**
   * Gate used by route guards: emits `true` when the feature is unlocked, otherwise opens the upgrade
   * modal and emits `false`. Awaits hydration first so an entitled deep-link is never wrongly blocked.
   */
  ensureAccess(feature: LicenseFeature): Observable<boolean> {
    return this.ensureHydrated().pipe(
      map(() => this.isAvailable(feature)),
      take(1),
      tap((unlocked) => {
        if (!unlocked) {
          this.openUpgradeModal(feature);
        }
      })
    );
  }

  /**
   * Locked subset of the supplied features, kept in sync with license changes. Drives the toolbox
   * "Pro" badges.
   */
  watchLockedFeatures(features: readonly LicenseFeature[]): Observable<Set<LicenseFeature>> {
    if (environment.cloudMode) {
      return of(new Set<LicenseFeature>());
    }

    return this.ensureHydrated().pipe(
      switchMap(() => this.license$),
      map(() => new Set(features.filter((feature) => !this.isAvailable(feature))))
    );
  }

  /**
   * Effective edition/tier currently in force, for passive UI such as the navbar edition badge.
   * Mirrors {@link isAvailable}'s liveness rules, so an unlicensed, inactive or lapsed install
   * reports Community and the badge never overstates the entitlement. Re-emits on license
   * import/removal. Cloud has no on-premise edition and reports Community (never shown there).
   */
  currentEdition$(): Observable<string> {
    if (environment.cloudMode) {
      return of(COMMUNITY_TIER);
    }

    return this.ensureHydrated().pipe(
      switchMap(() => this.license$),
      map(() => this.effectiveTier()),
      distinctUntilChanged()
    );
  }

  /**
   * Forces a fresh license lookup and reseeds the cache. Called on login so the whole app starts
   * with an up-to-date entitlement instead of waiting for the first gated access to hydrate it.
   */
  refresh(): Observable<CurrentLicense | null> {
    if (environment.cloudMode) {
      return of(null);
    }

    return this.startHydration();
  }

  /** Seeds the cache from a freshly imported license, so gated UI updates without a re-fetch. */
  seed(license: CurrentLicense): void {
    this.license.set(license);
  }

  /**
   * Clears the cached entitlement after a license removal, locking gated UI immediately.
   */
  clear(): void {
    if (environment.cloudMode) {
      return;
    }

    this.hydration$ = undefined;
    this.license.set(null);
  }

  /** Opens the upgrade showcase for a feature directly (e.g. a locked badge click). */
  promptUpgrade(feature: LicenseFeature): void {
    this.openUpgradeModal(feature);
  }

  /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  /** Tier discriminator in force now, or Community when unlicensed, inactive or lapsed. */
  private effectiveTier(): string {
    const license = this.license();
    if (!license || !license.is_active) {
      return COMMUNITY_TIER;
    }

    const days = remainingDays(license.entitlement.endDate, Date.now());
    if (days !== null && days < 0) {
      return COMMUNITY_TIER;
    }

    return license.entitlement.type || COMMUNITY_TIER;
  }

  /**
   * Resolves once the license is known, performing a single shared fetch the first time it is needed.
   * Already-hydrated callers resolve immediately; concurrent first-callers share one network request.
   */
  private ensureHydrated(): Observable<CurrentLicense | null> {
    if (environment.cloudMode) {
      return of(null);
    }

    const current = this.license();
    if (current !== undefined) {
      return of(current);
    }

    return this.hydration$ ?? this.startHydration();
  }

  /** Kicks off a shared license fetch that populates the cache; concurrent callers reuse it. */
  private startHydration(): Observable<CurrentLicense | null> {
    this.hydration$ = this.fetchLicense().pipe(
      tap((license) => this.license.set(license)),
      shareReplay(1)
    );

    return this.hydration$;
  }

  /** Single point that talks to the license endpoint; a failed lookup degrades safely to Community. */
  private fetchLicense(): Observable<CurrentLicense | null> {
    return this.licenseService.getCurrentLicense().pipe(
      catchError(() => of(null))
    );
  }

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
