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
import { TestBed, fakeAsync, flushMicrotasks } from '@angular/core/testing';
import { Router } from '@angular/router';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { of, throwError } from 'rxjs';

import { environment } from 'src/environments/environment';
import { PREMIUM_FEATURE_MODAL_RESULT } from 'src/app/core/components/dialog/premium-feature-modal/premium-feature-modal.component';

import { PremiumFeatureService } from './premium-feature.service';
import { LicenseService } from '../services/license.service';
import { LicenseEntitlements, LicenseFeature } from '../models/license.model';

/* ------------------------------------------------------------------------------------------------------------------ */

/** Community answer of `GET /rest/license/entitlements`. */
const COMMUNITY: LicenseEntitlements = { is_active: false, type: 'free', features: [] };

/**
 * Builds an entitlements payload. Defaults describe an active Business license that unlocks IPAM
 * and ISMS; every field can be overridden per scenario.
 */
function buildEntitlements(overrides: Partial<LicenseEntitlements> = {}): LicenseEntitlements {
  return {
    is_active: overrides.is_active ?? true,
    type: overrides.type ?? 'business',
    features: overrides.features ?? [LicenseFeature.Ipam, LicenseFeature.Isms]
  };
}

describe('PremiumFeatureService', () => {
  let service: PremiumFeatureService;
  let licenseService: jasmine.SpyObj<LicenseService>;
  let modalService: jasmine.SpyObj<NgbModal>;
  let router: jasmine.SpyObj<Router>;
  let originalCloudMode: boolean;

  /** Runs the effect that backs `toObservable(entitlements)`, so reactive streams emit the latest value. */
  const flushSignals = () => TestBed.flushEffects();

  /** Warms the cache from the mocked endpoint, the way login does, and arms it for later refreshes. */
  const hydrate = (entitlements: LicenseEntitlements) => {
    licenseService.getEntitlements.and.returnValue(of(entitlements));
    service.refresh().subscribe();
  };

  beforeEach(() => {
    originalCloudMode = environment.cloudMode;
    environment.cloudMode = false;

    licenseService = jasmine.createSpyObj<LicenseService>('LicenseService', ['getEntitlements']);
    // Sensible default: nothing licensed. Entitled scenarios override this before hydration.
    licenseService.getEntitlements.and.returnValue(of(COMMUNITY));

    modalService = jasmine.createSpyObj<NgbModal>('NgbModal', ['open']);
    router = jasmine.createSpyObj<Router>('Router', ['navigate', 'navigateByUrl'], { url: '/settings/license' });

    TestBed.configureTestingModule({
      providers: [
        PremiumFeatureService,
        { provide: LicenseService, useValue: licenseService },
        { provide: NgbModal, useValue: modalService },
        { provide: Router, useValue: router }
      ]
    });

    service = TestBed.inject(PremiumFeatureService);
  });

  afterEach(() => {
    environment.cloudMode = originalCloudMode;
  });

  it('is created', () => {
    expect(service).toBeTruthy();
  });

  /* ------------------------------------- isAvailable() — synchronous snapshot ------------------------------------- */

  describe('isAvailable() synchronous snapshot', () => {
    it('fails closed (locked) before the entitlements are hydrated', () => {
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeFalse();
    });

    it('is locked on the Community edition (no license)', () => {
      hydrate(COMMUNITY);
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeFalse();
    });

    it('is unlocked for a listed feature on an active license', () => {
      hydrate(buildEntitlements({ features: [LicenseFeature.Ipam] }));
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeTrue();
    });

    it('is locked for a feature the license does not include', () => {
      hydrate(buildEntitlements({ features: [LicenseFeature.Isms] }));
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeFalse();
    });

    it('is locked when the license is inactive, even if the feature is listed', () => {
      // `is_active` is the backend's verdict and already covers an expired license.
      hydrate(buildEntitlements({ is_active: false, features: [LicenseFeature.Ipam] }));
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeFalse();
    });

    it('evaluates each feature independently', () => {
      hydrate(buildEntitlements({ features: [LicenseFeature.Ipam] }));
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeTrue();
      expect(service.isAvailable(LicenseFeature.Isms)).toBeFalse();
      expect(service.isAvailable(LicenseFeature.Automations)).toBeFalse();
    });
  });

  /* -------------------------------------- isAvailable$() — reactive stream --------------------------------------- */

  describe('isAvailable$() reactive stream', () => {
    it('hydrates once and emits the current availability', () => {
      licenseService.getEntitlements.and.returnValue(of(buildEntitlements({ features: [LicenseFeature.Ipam] })));

      const seen: boolean[] = [];
      const sub = service.isAvailable$(LicenseFeature.Ipam).subscribe((v) => seen.push(v));
      flushSignals();

      expect(seen).toEqual([true]);
      sub.unsubscribe();
    });

    it('re-emits FALSE to an existing subscriber after clear() — the sidebar locks without a reload', () => {
      licenseService.getEntitlements.and.returnValue(of(buildEntitlements({ features: [LicenseFeature.Ipam] })));

      const seen: boolean[] = [];
      const sub = service.isAvailable$(LicenseFeature.Ipam).subscribe((v) => seen.push(v));
      flushSignals();
      expect(seen).toEqual([true]);

      service.clear();
      flushSignals();

      expect(seen).toEqual([true, false]);
      sub.unsubscribe();
    });

    it('re-emits TRUE to an existing subscriber after refresh() — an imported license unlocks live', () => {
      // Start locked (Community).
      const seen: boolean[] = [];
      const sub = service.isAvailable$(LicenseFeature.Ipam).subscribe((v) => seen.push(v));
      flushSignals();
      expect(seen).toEqual([false]);

      hydrate(buildEntitlements({ features: [LicenseFeature.Ipam] }));
      flushSignals();

      expect(seen).toEqual([false, true]);
      sub.unsubscribe();
    });

    it('does not emit duplicates while availability is unchanged', () => {
      licenseService.getEntitlements.and.returnValue(of(buildEntitlements({ features: [LicenseFeature.Ipam] })));

      const seen: boolean[] = [];
      const sub = service.isAvailable$(LicenseFeature.Ipam).subscribe((v) => seen.push(v));
      flushSignals();

      // A wider entitlement that still includes IPAM must not produce a second emission.
      hydrate(buildEntitlements({ features: [LicenseFeature.Ipam, LicenseFeature.Isms] }));
      flushSignals();

      expect(seen).toEqual([true]);
      sub.unsubscribe();
    });

    it('fails closed (emits false) when the entitlements lookup errors', () => {
      licenseService.getEntitlements.and.returnValue(throwError(() => new Error('network down')));

      const seen: boolean[] = [];
      const sub = service.isAvailable$(LicenseFeature.Ipam).subscribe((v) => seen.push(v));
      flushSignals();

      expect(seen).toEqual([false]);
      sub.unsubscribe();
    });

    it('tracks each feature separately from a single payload', () => {
      licenseService.getEntitlements.and.returnValue(of(buildEntitlements({ features: [LicenseFeature.Ipam] })));

      const ipam: boolean[] = [];
      const isms: boolean[] = [];
      const s1 = service.isAvailable$(LicenseFeature.Ipam).subscribe((v) => ipam.push(v));
      const s2 = service.isAvailable$(LicenseFeature.Isms).subscribe((v) => isms.push(v));
      flushSignals();

      expect(ipam).toEqual([true]);
      expect(isms).toEqual([false]);
      s1.unsubscribe();
      s2.unsubscribe();
    });
  });

  /* -------------------------- clear() — license removal (regression for the reload bug) -------------------------- */

  describe('clear() license removal', () => {
    it('asserts the de-entitled state WITHOUT another entitlements round-trip', () => {
      hydrate(buildEntitlements({ features: [LicenseFeature.Ipam] }));
      flushSignals();
      licenseService.getEntitlements.calls.reset();

      service.clear();

      // The core of the fix: removal must not re-derive entitlement from a cacheable GET.
      expect(licenseService.getEntitlements).not.toHaveBeenCalled();
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeFalse();
    });

    it('locks a subscriber that connects AFTER removal, still without re-fetching', () => {
      hydrate(buildEntitlements({ features: [LicenseFeature.Ipam] }));
      flushSignals();

      service.clear();
      licenseService.getEntitlements.calls.reset();

      const seen: boolean[] = [];
      const sub = service.isAvailable$(LicenseFeature.Ipam).subscribe((v) => seen.push(v));
      flushSignals();

      expect(seen).toEqual([false]);
      expect(licenseService.getEntitlements).not.toHaveBeenCalled();
      sub.unsubscribe();
    });

    it('is idempotent — clearing twice stays locked', () => {
      hydrate(buildEntitlements({ features: [LicenseFeature.Ipam] }));
      service.clear();
      service.clear();
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeFalse();
    });

    it('is a no-op in cloud mode (features stay entitled, no state touched)', () => {
      environment.cloudMode = true;

      service.clear();

      expect(service.isAvailable(LicenseFeature.Ipam)).toBeTrue();
      expect(licenseService.getEntitlements).not.toHaveBeenCalled();
    });
  });

  /* ------------------------------------ refresh() — login and license changes ------------------------------------ */

  describe('refresh() entitlements re-read', () => {
    it('reads license/entitlements and reflects the result synchronously', () => {
      licenseService.getEntitlements.and.returnValue(of(buildEntitlements({ features: [LicenseFeature.Ipam] })));

      service.refresh().subscribe();

      expect(licenseService.getEntitlements).toHaveBeenCalledTimes(1);
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeTrue();
    });

    it('re-reads on every call, so a license change is never served from the warm cache', () => {
      hydrate(buildEntitlements({ features: [LicenseFeature.Ipam] }));
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeTrue();

      hydrate(COMMUNITY);

      expect(licenseService.getEntitlements).toHaveBeenCalledTimes(2);
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeFalse();
    });

    it('does not reach the endpoint in cloud mode', () => {
      environment.cloudMode = true;

      service.refresh().subscribe();

      expect(licenseService.getEntitlements).not.toHaveBeenCalled();
    });
  });

  /* -------------------------------------------- hydration & caching ---------------------------------------------- */

  describe('hydration and caching', () => {
    it('performs a single shared fetch for concurrent first-time subscribers', () => {
      licenseService.getEntitlements.and.returnValue(of(buildEntitlements()));

      const s1 = service.isAvailable$(LicenseFeature.Ipam).subscribe();
      const s2 = service.isAvailable$(LicenseFeature.Isms).subscribe();
      flushSignals();

      expect(licenseService.getEntitlements).toHaveBeenCalledTimes(1);
      s1.unsubscribe();
      s2.unsubscribe();
    });

    it('does not re-fetch once the entitlements are hydrated', () => {
      licenseService.getEntitlements.and.returnValue(of(buildEntitlements()));

      service.isAvailable$(LicenseFeature.Ipam).subscribe().unsubscribe();
      service.isAvailable$(LicenseFeature.Isms).subscribe().unsubscribe();

      expect(licenseService.getEntitlements).toHaveBeenCalledTimes(1);
    });
  });

  /* ------------------------------------------ ensureAccess() — guards -------------------------------------------- */

  describe('ensureAccess() route-guard gate', () => {
    function stubModal(result: unknown) {
      modalService.open.and.returnValue({
        componentInstance: {},
        result: Promise.resolve(result)
      } as never);
    }

    it('emits true exactly once and does NOT open the modal when unlocked', () => {
      licenseService.getEntitlements.and.returnValue(of(buildEntitlements({ features: [LicenseFeature.Ipam] })));

      const seen: boolean[] = [];
      service.ensureAccess(LicenseFeature.Ipam).subscribe((v) => seen.push(v));

      expect(seen).toEqual([true]);
      expect(modalService.open).not.toHaveBeenCalled();
    });

    it('emits false and opens the upgrade modal when locked', () => {
      licenseService.getEntitlements.and.returnValue(of(COMMUNITY));
      stubModal(PREMIUM_FEATURE_MODAL_RESULT.later);

      const seen: boolean[] = [];
      service.ensureAccess(LicenseFeature.Ipam).subscribe((v) => seen.push(v));

      expect(seen).toEqual([false]);
      expect(modalService.open).toHaveBeenCalledTimes(1);
    });

    it('blocks access after a license removal (clear())', () => {
      hydrate(buildEntitlements({ features: [LicenseFeature.Ipam] }));
      service.clear();
      stubModal(PREMIUM_FEATURE_MODAL_RESULT.later);

      const seen: boolean[] = [];
      service.ensureAccess(LicenseFeature.Ipam).subscribe((v) => seen.push(v));

      expect(seen).toEqual([false]);
      expect(modalService.open).toHaveBeenCalledTimes(1);
    });
  });

  /* --------------------------------------- watchLockedFeatures() — badges ---------------------------------------- */

  describe('watchLockedFeatures() toolbox badges', () => {
    const WATCHED = [LicenseFeature.Ipam, LicenseFeature.Isms, LicenseFeature.DocumentGenerator];
    const latest = (sets: Set<LicenseFeature>[]) => sets[sets.length - 1];

    it('reports only the locked subset of the watched features', () => {
      licenseService.getEntitlements.and.returnValue(of(buildEntitlements({ features: [LicenseFeature.Ipam] })));

      const sets: Set<LicenseFeature>[] = [];
      const sub = service.watchLockedFeatures(WATCHED).subscribe((s) => sets.push(s));
      flushSignals();

      expect(latest(sets).has(LicenseFeature.Ipam)).toBeFalse();
      expect(latest(sets).has(LicenseFeature.Isms)).toBeTrue();
      expect(latest(sets).has(LicenseFeature.DocumentGenerator)).toBeTrue();
      sub.unsubscribe();
    });

    it('locks every watched feature again after clear()', () => {
      licenseService.getEntitlements.and.returnValue(of(buildEntitlements({ features: WATCHED })));

      const sets: Set<LicenseFeature>[] = [];
      const sub = service.watchLockedFeatures(WATCHED).subscribe((s) => sets.push(s));
      flushSignals();
      expect(latest(sets).size).toBe(0);

      service.clear();
      flushSignals();

      expect(latest(sets).size).toBe(WATCHED.length);
      sub.unsubscribe();
    });

    it('emits an empty set in cloud mode', () => {
      environment.cloudMode = true;

      const sets: Set<LicenseFeature>[] = [];
      service.watchLockedFeatures(WATCHED).subscribe((s) => sets.push(s));

      expect(sets.length).toBe(1);
      expect(sets[0].size).toBe(0);
      expect(licenseService.getEntitlements).not.toHaveBeenCalled();
    });
  });

  /* ------------------------------------------ currentEdition$() — badge ------------------------------------------ */

  describe('currentEdition$() navbar edition badge', () => {
    it('reports the licensed tier while the license is active', () => {
      licenseService.getEntitlements.and.returnValue(of(buildEntitlements({ type: 'business' })));

      const seen: string[] = [];
      const sub = service.currentEdition$().subscribe((v) => seen.push(v));
      flushSignals();

      expect(seen).toEqual(['business']);
      sub.unsubscribe();
    });

    it('falls back to Community for an inactive license, whatever tier it names', () => {
      licenseService.getEntitlements.and.returnValue(of(buildEntitlements({ is_active: false, type: 'corporate' })));

      const seen: string[] = [];
      const sub = service.currentEdition$().subscribe((v) => seen.push(v));
      flushSignals();

      expect(seen).toEqual(['free']);
      sub.unsubscribe();
    });
  });

  /* --------------------------------------- promptUpgrade() — upgrade modal --------------------------------------- */

  describe('promptUpgrade() upgrade showcase', () => {
    it('opens the showcase populated from the feature content', () => {
      const instance: Record<string, unknown> = {};
      modalService.open.and.returnValue({ componentInstance: instance, result: new Promise(() => {}) } as never);

      service.promptUpgrade(LicenseFeature.Ipam);

      expect(modalService.open).toHaveBeenCalledTimes(1);
      expect(instance['title']).toBeTruthy();
    });

    it('routes straight to license management when a feature has no showcase content', () => {
      service.promptUpgrade('unknown_feature' as LicenseFeature);

      expect(router.navigate).toHaveBeenCalledWith(['/settings/license']);
      expect(modalService.open).not.toHaveBeenCalled();
    });

    it('navigates to license management when the user chooses to upgrade', fakeAsync(() => {
      modalService.open.and.returnValue({
        componentInstance: {},
        result: Promise.resolve(PREMIUM_FEATURE_MODAL_RESULT.upgrade)
      } as never);

      service.promptUpgrade(LicenseFeature.Ipam);
      flushMicrotasks();

      expect(router.navigate).toHaveBeenCalledWith(['/settings/license']);
    }));

    it('returns the user to the originating page when the showcase is dismissed', fakeAsync(() => {
      modalService.open.and.returnValue({
        componentInstance: {},
        result: Promise.reject(PREMIUM_FEATURE_MODAL_RESULT.later)
      } as never);

      service.promptUpgrade(LicenseFeature.Ipam);
      flushMicrotasks();

      expect(router.navigateByUrl).toHaveBeenCalledWith('/settings/license');
    }));
  });

  /* ---------------------------------------------- cloud mode ----------------------------------------------------- */

  describe('cloud mode', () => {
    beforeEach(() => {
      environment.cloudMode = true;
    });

    it('reports every feature as available synchronously', () => {
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeTrue();
      expect(service.isAvailable(LicenseFeature.Isms)).toBeTrue();
    });

    it('emits true from isAvailable$ without hitting the entitlements endpoint', () => {
      const seen: boolean[] = [];
      service.isAvailable$(LicenseFeature.Ipam).subscribe((v) => seen.push(v));

      expect(seen).toEqual([true]);
      expect(licenseService.getEntitlements).not.toHaveBeenCalled();
    });

    it('grants access from ensureAccess without opening the modal', () => {
      const seen: boolean[] = [];
      service.ensureAccess(LicenseFeature.Ipam).subscribe((v) => seen.push(v));

      expect(seen).toEqual([true]);
      expect(modalService.open).not.toHaveBeenCalled();
    });
  });
});
