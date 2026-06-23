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
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, OnDestroy, OnInit } from '@angular/core';
import { HttpResponse } from '@angular/common/http';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { Observable, ReplaySubject } from 'rxjs';
import { finalize, switchMap, takeUntil } from 'rxjs/operators';
import { FileSaverService } from 'ngx-filesaver';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { LicenseCatalogModalComponent } from './components/license-catalog-modal/license-catalog-modal.component';
import { LicenseService } from './services/license.service';
import {
  CurrentLicense,
  LICENSE_STATUS_MESSAGES,
  LicenseEdition,
  LicenseEntitlement,
  LicenseFeature,
  LicenseVerificationStatus
} from './models/license.model';
import { parseContentDispositionFilename, readLicenseFile, remainingDays, resolveEdition } from './utils/license.util';
/* ------------------------------------------------------------------------------------------------------------------ */

const ACTIVATION_REQUEST_FILENAME = 'datagerry-activation-request.txt';

/** Session flag so the premium catalogue greeting opens at most once per browser session. */
const CATALOG_SEEN_KEY = 'dg.license.catalog.seen';


@Component({
  selector: 'cmdb-license-management',
  templateUrl: './license-management.component.html',
  styleUrls: ['./license-management.component.scss'],
  standalone: false,
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class LicenseManagementComponent implements OnInit, OnDestroy {
  public readonly LicenseEdition = LicenseEdition;
  public readonly isLoading$: Observable<boolean> = this.loaderService.isLoading$;

  public edition: LicenseEdition = LicenseEdition.Community;
  public entitlement: LicenseEntitlement | null = null;
  public features: LicenseFeature[] = [];
  public remainingDays: number | null = null;
  public rejectionMessage: string | null = null;
  public loadError = false;

  public wizardActive = false;
  public wizardGenerated = false;
  public importing = false;
  public activatedEntitlement: LicenseEntitlement | null = null;

  /** The catalogue is an upgrade upsell, so only offer it on locked (non Self-Hosted) editions. */
  public get showCatalogTrigger(): boolean {
    return !this.loadError && this.edition !== LicenseEdition.SelfHosted;
  }

  private readonly subscriber = new ReplaySubject<void>(1);

  constructor(
    private readonly licenseService: LicenseService,
    private readonly loaderService: LoaderService,
    private readonly toast: ToastService,
    private readonly fileSaver: FileSaverService,
    private readonly modalService: NgbModal,
    private readonly cdr: ChangeDetectorRef
  ) {}

  /* -------------------------------------------------- LIFE CYCLE -------------------------------------------------- */

  public ngOnInit(): void {
    this.loadCurrentLicense();
  }

  public ngOnDestroy(): void {
    this.subscriber.next();
    this.subscriber.complete();
  }

  /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

  public onRetry(): void {
    this.loadCurrentLicense();
  }

  /** Manually opens the Self-Hosted feature catalogue (bypasses the once-per-session auto-open). */
  public onShowCatalog(): void {
    this.openCatalogModal();
  }

  public onGenerateActivationRequest(): void {
    this.loaderService.show();

    this.licenseService.downloadActivationRequest()
      .pipe(
        takeUntil(this.subscriber),
        finalize(() => this.loaderService.hide())
      )
      .subscribe({
        next: (response) => this.saveActivationRequest(response),
        // Blob error bodies carry no parsed message, so fall back to a static one.
        error: (err) => this.toast.error(err?.error?.message ?? 'The activation request could not be downloaded.')
      });
  }

  public onActivateLicense(file: File): void {
    this.importing = true;
    this.loaderService.show();

    readLicenseFile(file)
      .pipe(
        switchMap((content) => {
          const blob = content.trim();

          if (!blob) {
            throw new Error('The selected license file is empty.');
          }

          return this.licenseService.importLicense(blob);
        }),
        takeUntil(this.subscriber),
        finalize(() => {
          this.importing = false;
          this.loaderService.hide();
          this.cdr.markForCheck();
        })
      )
      .subscribe({
        next: (license) => this.onImportSuccess(license),
        error: (err) => this.toast.error(err?.error?.message ?? 'The license could not be imported.')
      });
  }

  public onWizardFinished(): void {
    this.wizardActive = false;
    this.activatedEntitlement = null;
    this.cdr.markForCheck();
  }

  /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  private loadCurrentLicense(): void {
    this.loadError = false;
    this.loaderService.show();

    this.licenseService.getCurrentLicense()
      .pipe(
        takeUntil(this.subscriber),
        finalize(() => this.loaderService.hide())
      )
      .subscribe({
        next: (license) => {
          this.setLicenseState(license);
          this.wizardActive = this.usesWizard(this.edition);
          this.cdr.markForCheck();
          this.maybeShowCatalogModal();
        },
        error: (err) => {
          this.loadError = true;
          this.toast.error(err?.error?.message ?? 'The current license could not be loaded.');
          this.cdr.markForCheck();
        }
      });
  }

  private onImportSuccess(license: CurrentLicense): void {
    this.toast.success('License imported successfully.');
    this.setLicenseState(license);
    // Keep the wizard mounted and surface its completion step.
    this.activatedEntitlement = license.entitlement;
    this.cdr.markForCheck();
  }

  private setLicenseState(license: CurrentLicense): void {
    const entitlement = license.entitlement;

    this.entitlement = entitlement;
    this.edition = resolveEdition(license);
    this.features = entitlement.features;
    this.remainingDays = remainingDays(entitlement.endDate, Date.now());
    this.rejectionMessage = this.resolveRejectionMessage(license.status);
  }

  private saveActivationRequest(response: HttpResponse<Blob>): void {
    const blob = response?.body;

    if (!blob) {
      this.toast.error('The activation request response was empty.');
      return;
    }

    const filename = parseContentDispositionFilename(response.headers.get('Content-Disposition'))
      ?? ACTIVATION_REQUEST_FILENAME;

    this.fileSaver.save(blob, filename);
    this.wizardGenerated = true;
    this.toast.success('Activation request downloaded.');
    this.cdr.markForCheck();
  }

  private usesWizard(edition: LicenseEdition): boolean {
    return edition === LicenseEdition.Community || edition === LicenseEdition.Expired;
  }

  private resolveRejectionMessage(status: LicenseVerificationStatus | null): string | null {
    if (!status || status === LicenseVerificationStatus.Valid) {
      return null;
    }

    return LICENSE_STATUS_MESSAGES[status] || null;
  }

  /**
   * Greets the user with the premium catalogue when the edition is locked (Community/Expired).
   * Self-Hosted instances already have every feature, and the dialog opens at most once per session.
   */
  private maybeShowCatalogModal(): void {
    if (this.edition === LicenseEdition.SelfHosted || this.hasSeenCatalog()) {
      return;
    }

    this.markCatalogSeen();
    this.openCatalogModal();
  }

  private openCatalogModal(): void {
    const modalRef = this.modalService.open(LicenseCatalogModalComponent, {
      size: 'xl',
      centered: true,
      windowClass: 'license-catalog-window',
      modalDialogClass: 'license-catalog-dialog',
      ariaLabelledBy: 'license-catalog-title'
    });

    const instance = modalRef.componentInstance as LicenseCatalogModalComponent;
    instance.edition = this.edition;
    instance.features = this.features;

    // Continue, the close button and the backdrop all just reveal the page — swallow the rejection.
    modalRef.result.catch(() => undefined);
  }

  /** Whether the greeting already ran this session; degrades to "not seen" when storage is blocked. */
  private hasSeenCatalog(): boolean {
    try {
      return sessionStorage.getItem(CATALOG_SEEN_KEY) === '1';
    } catch {
      return false;
    }
  }

  private markCatalogSeen(): void {
    try {
      sessionStorage.setItem(CATALOG_SEEN_KEY, '1');
    } catch {
      // Storage can be unavailable (private mode, quota); the greeting simply shows again next load.
    }
  }
}
