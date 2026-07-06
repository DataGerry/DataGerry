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
import { CurrentLicense, LicenseFeature, LicenseVerificationStatus } from '../models/license.model';

/* ------------------------------------------------------------------------------------------------------------------ */

const DAY_MS = 86_400_000;

/**
 * Builds a domain-model license. Defaults describe an active, perpetual Business license that
 * unlocks IPAM and ISMS; every field can be overridden per scenario.
 */
function buildLicense(overrides: {
  is_active?: boolean;
  status?: LicenseVerificationStatus | null;
  type?: string;
  features?: LicenseFeature[];
  endDate?: number;
} = {}): CurrentLicense {
  return {
    is_active: overrides.is_active ?? true,
    status: overrides.status ?? LicenseVerificationStatus.Valid,
    entitlement: {
      hmac: 'hmac',
      startDate: 0,
      endDate: overrides.endDate ?? 0, // 0 = perpetual
      subId: 'sub-1',
      licenseId: 'lic-1',
      operationUsage: 0,
      duration: 0,
      type: overrides.type ?? 'business',
      features: overrides.features ?? [LicenseFeature.Ipam, LicenseFeature.Isms]
    }
  };
}

describe('PremiumFeatureService', () => {
  let service: PremiumFeatureService;
  let licenseService: jasmine.SpyObj<LicenseService>;
  let modalService: jasmine.SpyObj<NgbModal>;
  let router: jasmine.SpyObj<Router>;
  let originalCloudMode: boolean;

  /** Runs the effect that backs `toObservable(license)`, so reactive streams emit the latest value. */
  const flushSignals = () => TestBed.flushEffects();

  beforeEach(() => {
    originalCloudMode = environment.cloudMode;
    environment.cloudMode = false;

    licenseService = jasmine.createSpyObj<LicenseService>('LicenseService', ['getCurrentLicense']);
    // Sensible default: nothing licensed. Entitled scenarios override this before hydration.
    licenseService.getCurrentLicense.and.returnValue(of(null as unknown as CurrentLicense));

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
    it('fails closed (locked) before the license is hydrated', () => {
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeFalse();
    });

    it('is locked on the Community edition (no license)', () => {
      service.clear();
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeFalse();
    });

    it('is unlocked for a listed feature on an active perpetual license', () => {
      service.seed(buildLicense({ features: [LicenseFeature.Ipam] }));
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeTrue();
    });

    it('is locked for a feature the license does not include', () => {
      service.seed(buildLicense({ features: [LicenseFeature.Isms] }));
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeFalse();
    });

    it('is locked when the license is inactive, even if the feature is listed', () => {
      service.seed(buildLicense({ is_active: false, features: [LicenseFeature.Ipam] }));
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeFalse();
    });

    it('is locked when the license has expired, even if the feature is listed', () => {
      service.seed(buildLicense({ features: [LicenseFeature.Ipam], endDate: Date.now() - 2 * DAY_MS }));
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeFalse();
    });

    it('is unlocked when a dated license is still within its validity window', () => {
      service.seed(buildLicense({ features: [LicenseFeature.Ipam], endDate: Date.now() + 30 * DAY_MS }));
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeTrue();
    });

    it('evaluates each feature independently', () => {
      service.seed(buildLicense({ features: [LicenseFeature.Ipam] }));
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeTrue();
      expect(service.isAvailable(LicenseFeature.Isms)).toBeFalse();
      expect(service.isAvailable(LicenseFeature.Automations)).toBeFalse();
    });
  });

  /* -------------------------------------- isAvailable$() — reactive stream --------------------------------------- */

  describe('isAvailable$() reactive stream', () => {
    it('hydrates once and emits the current availability', () => {
      licenseService.getCurrentLicense.and.returnValue(of(buildLicense({ features: [LicenseFeature.Ipam] })));

      const seen: boolean[] = [];
      const sub = service.isAvailable$(LicenseFeature.Ipam).subscribe((v) => seen.push(v));
      flushSignals();

      expect(seen).toEqual([true]);
      sub.unsubscribe();
    });

    it('re-emits FALSE to an existing subscriber after clear() — the sidebar locks without a reload', () => {
      licenseService.getCurrentLicense.and.returnValue(of(buildLicense({ features: [LicenseFeature.Ipam] })));

      const seen: boolean[] = [];
      const sub = service.isAvailable$(LicenseFeature.Ipam).subscribe((v) => seen.push(v));
      flushSignals();
      expect(seen).toEqual([true]);

      service.clear();
      flushSignals();

      expect(seen).toEqual([true, false]);
      sub.unsubscribe();
    });

    it('re-emits TRUE to an existing subscriber after seed() — an imported license unlocks live', () => {
      // Start locked (Community).
      const seen: boolean[] = [];
      const sub = service.isAvailable$(LicenseFeature.Ipam).subscribe((v) => seen.push(v));
      flushSignals();
      expect(seen).toEqual([false]);

      service.seed(buildLicense({ features: [LicenseFeature.Ipam] }));
      flushSignals();

      expect(seen).toEqual([false, true]);
      sub.unsubscribe();
    });

    it('does not emit duplicates while availability is unchanged', () => {
      licenseService.getCurrentLicense.and.returnValue(of(buildLicense({ features: [LicenseFeature.Ipam] })));

      const seen: boolean[] = [];
      const sub = service.isAvailable$(LicenseFeature.Ipam).subscribe((v) => seen.push(v));
      flushSignals();

      // A different license object that still includes IPAM must not produce a second emission.
      service.seed(buildLicense({ features: [LicenseFeature.Ipam, LicenseFeature.Isms] }));
      flushSignals();

      expect(seen).toEqual([true]);
      sub.unsubscribe();
    });

    it('fails closed (emits false) when the license lookup errors', () => {
      licenseService.getCurrentLicense.and.returnValue(throwError(() => new Error('network down')));

      const seen: boolean[] = [];
      const sub = service.isAvailable$(LicenseFeature.Ipam).subscribe((v) => seen.push(v));
      flushSignals();

      expect(seen).toEqual([false]);
      sub.unsubscribe();
    });

    it('tracks each feature separately from a single license', () => {
      licenseService.getCurrentLicense.and.returnValue(of(buildLicense({ features: [LicenseFeature.Ipam] })));

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
    it('asserts the de-entitled state WITHOUT another license/current round-trip', () => {
      licenseService.getCurrentLicense.and.returnValue(of(buildLicense({ features: [LicenseFeature.Ipam] })));
      // Hydrate first so the cache is warm and entitled.
      service.isAvailable$(LicenseFeature.Ipam).subscribe().unsubscribe();
      flushSignals();
      licenseService.getCurrentLicense.calls.reset();

      service.clear();

      // The core of the fix: removal must not re-derive entitlement from a cacheable GET.
      expect(licenseService.getCurrentLicense).not.toHaveBeenCalled();
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeFalse();
    });

    it('locks a subscriber that connects AFTER removal, still without re-fetching', () => {
      licenseService.getCurrentLicense.and.returnValue(of(buildLicense({ features: [LicenseFeature.Ipam] })));
      service.isAvailable$(LicenseFeature.Ipam).subscribe().unsubscribe();
      flushSignals();

      service.clear();
      licenseService.getCurrentLicense.calls.reset();

      const seen: boolean[] = [];
      const sub = service.isAvailable$(LicenseFeature.Ipam).subscribe((v) => seen.push(v));
      flushSignals();

      expect(seen).toEqual([false]);
      expect(licenseService.getCurrentLicense).not.toHaveBeenCalled();
      sub.unsubscribe();
    });

    it('is idempotent — clearing twice stays locked', () => {
      service.seed(buildLicense({ features: [LicenseFeature.Ipam] }));
      service.clear();
      service.clear();
      expect(service.isAvailable(LicenseFeature.Ipam)).toBeFalse();
    });

    it('is a no-op in cloud mode (features stay entitled, no state touched)', () => {
      environment.cloudMode = true;

      service.clear();

      expect(service.isAvailable(LicenseFeature.Ipam)).toBeTrue();
      expect(licenseService.getCurrentLicense).not.toHaveBeenCalled();
    });
  });

  /* ------------------------------------------- seed() — license import ------------------------------------------- */

  describe('seed() license import', () => {
    it('reflects the imported license synchronously without a fetch', () => {
      service.seed(buildLicense({ features: [LicenseFeature.Ipam] }));

      expect(service.isAvailable(LicenseFeature.Ipam)).toBeTrue();
      expect(licenseService.getCurrentLicense).not.toHaveBeenCalled();
    });

    it('unlocks a subscriber that connected while still on Community', () => {
      const seen: boolean[] = [];
      const sub = service.isAvailable$(LicenseFeature.Isms).subscribe((v) => seen.push(v));
      flushSignals();
      expect(seen).toEqual([false]);

      service.seed(buildLicense({ features: [LicenseFeature.Isms] }));
      flushSignals();

      expect(seen).toEqual([false, true]);
      sub.unsubscribe();
    });
  });

  /* -------------------------------------------- hydration & caching ---------------------------------------------- */

  describe('hydration and caching', () => {
    it('performs a single shared fetch for concurrent first-time subscribers', () => {
      licenseService.getCurrentLicense.and.returnValue(of(buildLicense()));

      const s1 = service.isAvailable$(LicenseFeature.Ipam).subscribe();
      const s2 = service.isAvailable$(LicenseFeature.Isms).subscribe();
      flushSignals();

      expect(licenseService.getCurrentLicense).toHaveBeenCalledTimes(1);
      s1.unsubscribe();
      s2.unsubscribe();
    });

    it('does not re-fetch once the license is hydrated', () => {
      licenseService.getCurrentLicense.and.returnValue(of(buildLicense()));

      service.isAvailable$(LicenseFeature.Ipam).subscribe().unsubscribe();
      service.isAvailable$(LicenseFeature.Isms).subscribe().unsubscribe();

      expect(licenseService.getCurrentLicense).toHaveBeenCalledTimes(1);
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
      licenseService.getCurrentLicense.and.returnValue(of(buildLicense({ features: [LicenseFeature.Ipam] })));

      const seen: boolean[] = [];
      service.ensureAccess(LicenseFeature.Ipam).subscribe((v) => seen.push(v));

      expect(seen).toEqual([true]);
      expect(modalService.open).not.toHaveBeenCalled();
    });

    it('emits false and opens the upgrade modal when locked', () => {
      licenseService.getCurrentLicense.and.returnValue(of(null as unknown as CurrentLicense));
      stubModal(PREMIUM_FEATURE_MODAL_RESULT.later);

      const seen: boolean[] = [];
      service.ensureAccess(LicenseFeature.Ipam).subscribe((v) => seen.push(v));

      expect(seen).toEqual([false]);
      expect(modalService.open).toHaveBeenCalledTimes(1);
    });

    it('blocks access after a license removal (clear())', () => {
      service.seed(buildLicense({ features: [LicenseFeature.Ipam] }));
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
      licenseService.getCurrentLicense.and.returnValue(of(buildLicense({ features: [LicenseFeature.Ipam] })));

      const sets: Set<LicenseFeature>[] = [];
      const sub = service.watchLockedFeatures(WATCHED).subscribe((s) => sets.push(s));
      flushSignals();

      expect(latest(sets).has(LicenseFeature.Ipam)).toBeFalse();
      expect(latest(sets).has(LicenseFeature.Isms)).toBeTrue();
      expect(latest(sets).has(LicenseFeature.DocumentGenerator)).toBeTrue();
      sub.unsubscribe();
    });

    it('locks every watched feature again after clear()', () => {
      licenseService.getCurrentLicense.and.returnValue(of(buildLicense({ features: WATCHED })));

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
      expect(licenseService.getCurrentLicense).not.toHaveBeenCalled();
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

    it('emits true from isAvailable$ without hitting the license endpoint', () => {
      const seen: boolean[] = [];
      service.isAvailable$(LicenseFeature.Ipam).subscribe((v) => seen.push(v));

      expect(seen).toEqual([true]);
      expect(licenseService.getCurrentLicense).not.toHaveBeenCalled();
    });

    it('grants access from ensureAccess without opening the modal', () => {
      const seen: boolean[] = [];
      service.ensureAccess(LicenseFeature.Ipam).subscribe((v) => seen.push(v));

      expect(seen).toEqual([true]);
      expect(modalService.open).not.toHaveBeenCalled();
    });
  });
});
