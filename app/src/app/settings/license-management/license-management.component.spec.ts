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
import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { FileSaverService } from 'ngx-filesaver';
import { of, throwError } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { DeleteModalConfig, DeleteModalService } from 'src/app/core/services/delete-modal.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { LicenseManagementComponent } from './license-management.component';
import { LicenseService } from './services/license.service';
import { PremiumFeatureService } from './premium-feature/premium-feature.service';
import { CurrentLicense, LicenseFeature, LicenseVerificationStatus } from './models/license.model';

/* ------------------------------------------------------------------------------------------------------------------ */

function buildLicense(features: LicenseFeature[], type = 'business'): CurrentLicense {
  return {
    is_active: true,
    status: LicenseVerificationStatus.Valid,
    entitlement: {
      hmac: 'hmac',
      startDate: 0,
      endDate: 0,
      subId: 'sub-1',
      licenseId: 'lic-1',
      operationUsage: 0,
      duration: 0,
      type,
      features
    }
  };
}

/** The Community "free fallback" license the backend returns after a removal. */
const COMMUNITY_LICENSE = buildLicense([], 'free');

describe('LicenseManagementComponent — gating cache wiring', () => {
  let fixture: ComponentFixture<LicenseManagementComponent>;
  let component: LicenseManagementComponent;

  let licenseService: jasmine.SpyObj<LicenseService>;
  let premiumFeature: jasmine.SpyObj<PremiumFeatureService>;
  let toast: jasmine.SpyObj<ToastService>;
  let loader: jasmine.SpyObj<LoaderService>;
  let deleteModal: jasmine.SpyObj<DeleteModalService>;

  beforeEach(async () => {
    licenseService = jasmine.createSpyObj<LicenseService>('LicenseService',
      ['getCurrentLicense', 'deleteCurrentLicense', 'importLicense', 'generateActivationKey']);
    premiumFeature = jasmine.createSpyObj<PremiumFeatureService>('PremiumFeatureService', ['seed', 'clear']);
    toast = jasmine.createSpyObj<ToastService>('ToastService', ['error', 'success']);
    loader = jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide'], { isLoading$: of(false) });
    deleteModal = jasmine.createSpyObj<DeleteModalService>('DeleteModalService', ['confirmDelete']);

    await TestBed.configureTestingModule({
      declarations: [LicenseManagementComponent],
      providers: [
        { provide: LicenseService, useValue: licenseService },
        { provide: PremiumFeatureService, useValue: premiumFeature },
        { provide: ToastService, useValue: toast },
        { provide: LoaderService, useValue: loader },
        { provide: DeleteModalService, useValue: deleteModal },
        { provide: NgbModal, useValue: jasmine.createSpyObj('NgbModal', ['open']) },
        { provide: FileSaverService, useValue: jasmine.createSpyObj('FileSaverService', ['save']) },
        { provide: ActivatedRoute, useValue: { snapshot: { data: {} } } }
      ],
      schemas: [NO_ERRORS_SCHEMA]
    })
      // Bypass the real template: this suite tests component logic, not markup.
      .overrideTemplate(LicenseManagementComponent, '')
      .compileComponents();

    fixture = TestBed.createComponent(LicenseManagementComponent);
    component = fixture.componentInstance;
    // Intentionally NOT calling detectChanges()/ngOnInit — each test drives one handler in isolation.
  });

  /* ------------------------------------------------ REMOVAL FLOW ------------------------------------------------- */

  describe('license removal', () => {
    it('clears the gating cache and reloads the license on a successful delete', () => {
      deleteModal.confirmDelete.and.callFake((config: DeleteModalConfig) => {
        config.onConfirm();
        return Promise.resolve();
      });
      licenseService.deleteCurrentLicense.and.returnValue(of(void 0));
      licenseService.getCurrentLicense.and.returnValue(of(COMMUNITY_LICENSE));

      component.onDeleteLicense();

      expect(licenseService.deleteCurrentLicense).toHaveBeenCalledTimes(1);
      expect(premiumFeature.clear).toHaveBeenCalledTimes(1);
      // The gate is cleared directly; it must not be re-derived from a fetch.
      expect(premiumFeature.seed).not.toHaveBeenCalled();
      expect(toast.success).toHaveBeenCalled();
      // The component still refreshes its own displayed edition.
      expect(licenseService.getCurrentLicense).toHaveBeenCalled();
    });

    it('does not clear the gating cache when the delete fails', () => {
      deleteModal.confirmDelete.and.callFake((config: DeleteModalConfig) => {
        config.onConfirm();
        return Promise.resolve();
      });
      licenseService.deleteCurrentLicense.and.returnValue(throwError(() => ({ error: { message: 'Delete failed' } })));

      component.onDeleteLicense();

      expect(toast.error).toHaveBeenCalledWith('Delete failed');
      expect(premiumFeature.clear).not.toHaveBeenCalled();
    });

    it('does nothing until the destructive action is confirmed', () => {
      // Confirmation modal opened but the user has not confirmed yet.
      deleteModal.confirmDelete.and.stub();

      component.onDeleteLicense();

      expect(deleteModal.confirmDelete).toHaveBeenCalledTimes(1);
      expect(licenseService.deleteCurrentLicense).not.toHaveBeenCalled();
      expect(premiumFeature.clear).not.toHaveBeenCalled();
    });
  });

  /* ------------------------------------------------ IMPORT FLOW -------------------------------------------------- */

  describe('license import', () => {
    it('seeds the gating cache from the imported license (no re-fetch)', fakeAsync(() => {
      const license = buildLicense([LicenseFeature.Ipam]);
      licenseService.importLicense.and.returnValue(of(license));
      const file = { text: () => Promise.resolve('license-blob') } as unknown as File;

      component.onActivateLicense(file);
      tick();

      expect(licenseService.importLicense).toHaveBeenCalledWith('license-blob');
      expect(premiumFeature.seed).toHaveBeenCalledWith(license);
      expect(premiumFeature.clear).not.toHaveBeenCalled();
      expect(toast.success).toHaveBeenCalled();
    }));

    it('does not seed when the import request fails', fakeAsync(() => {
      licenseService.importLicense.and.returnValue(throwError(() => ({ error: { message: 'Invalid license' } })));
      const file = { text: () => Promise.resolve('license-blob') } as unknown as File;

      component.onActivateLicense(file);
      tick();

      expect(toast.error).toHaveBeenCalledWith('Invalid license');
      expect(premiumFeature.seed).not.toHaveBeenCalled();
    }));

    it('rejects an empty license file without calling the import endpoint', fakeAsync(() => {
      const file = { text: () => Promise.resolve('   ') } as unknown as File;

      component.onActivateLicense(file);
      tick();

      expect(licenseService.importLicense).not.toHaveBeenCalled();
      expect(premiumFeature.seed).not.toHaveBeenCalled();
      expect(toast.error).toHaveBeenCalled();
    }));
  });
});
