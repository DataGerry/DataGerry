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
import { ActivatedRoute } from '@angular/router';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { Observable, ReplaySubject } from 'rxjs';
import { finalize, switchMap, takeUntil } from 'rxjs/operators';
import { FileSaverService } from 'ngx-filesaver';

import { LoaderService } from 'src/app/core/services/loader.service';
import { DeleteModalService } from 'src/app/core/services/delete-modal.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { LicenseCatalogModalComponent } from './components/license-catalog-modal/license-catalog-modal.component';
import { PremiumFeatureService } from './premium-feature/premium-feature.service';
import { LicenseService } from './services/license.service';
import { ResolvedLicense } from './services/license-resolver.service';
import {
  CurrentLicense,
  LICENSE_STATUS_MESSAGES,
  LICENSE_STATUS_TITLES,
  LICENSE_TIER_LABELS,
  LicenseEdition,
  LicenseEntitlement,
  LicenseFeature,
  LicenseTier,
  LicenseVerificationStatus
} from './models/license.model';
import { readLicenseFile, remainingDays, resolveEdition } from './utils/license.util';
/* ------------------------------------------------------------------------------------------------------------------ */

const ACTIVATION_REQUEST_FILENAME = 'datagerry-activation-request.txt';


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
  public rejectionTitle = 'License warning';
  public rejectionIcon = 'fas fa-triangle-exclamation';
  public loadError = false;
  /** False until the first license fetch resolves, so the view never renders before data exists. */
  public loaded = false;

  public wizardActive = false;
  public wizardGenerated = false;
  public activationKey: string | null = null;
  public importing = false;
  public activatedEntitlement: LicenseEntitlement | null = null;

  /** The catalogue is an upgrade upsell, so only offer it on locked (non Self-Hosted) editions. */
  public get showCatalogTrigger(): boolean {
    return this.loaded && !this.loadError && this.edition !== LicenseEdition.SelfHosted;
  }

  /** A license can be removed only once it is verified and active (the overview card is on screen). */
  public get canDeleteLicense(): boolean {
    return !this.loadError && !this.wizardActive && this.edition === LicenseEdition.SelfHosted;
  }

  /**
   * True while re-importing from an active license: the existing license is still in place, so the
   * wizard can be abandoned to return to the overview. The first-time (Community/Expired) wizard has
   * no overview to fall back to, so it is never cancellable.
   */
  public get canCancelImport(): boolean {
    return !this.loadError && this.wizardActive && this.edition === LicenseEdition.SelfHosted;
  }

  private readonly subscriber = new ReplaySubject<void>(1);

  constructor(
    private readonly licenseService: LicenseService,
    private readonly loaderService: LoaderService,
    private readonly toast: ToastService,
    private readonly fileSaver: FileSaverService,
    private readonly modalService: NgbModal,
    private readonly deleteModal: DeleteModalService,
    private readonly route: ActivatedRoute,
    private readonly cdr: ChangeDetectorRef,
    private readonly premiumFeatureService: PremiumFeatureService
  ) {}

  /* -------------------------------------------------- LIFE CYCLE -------------------------------------------------- */

  public ngOnInit(): void {
    this.applyResolvedLicense();
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

    this.licenseService.generateActivationKey()
      .pipe(
        takeUntil(this.subscriber),
        finalize(() => this.loaderService.hide())
      )
      .subscribe({
        next: (key) => this.onActivationKeyGenerated(key),
        // Text error bodies carry no parsed message, so fall back to a static one.
        error: (err) => this.toast.error(err?.error?.message ?? 'The activation request could not be generated.')
      });
  }

  /** Saves the already-generated activation request as a text file, reusing the displayed key. */
  public onDownloadActivationRequest(): void {
    if (!this.activationKey) {
      return;
    }

    const blob = new Blob([this.activationKey], { type: 'text/plain;charset=utf-8' });
    this.fileSaver.save(blob, ACTIVATION_REQUEST_FILENAME);
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
    this.activationKey = null;
    this.activatedEntitlement = null;
    this.cdr.markForCheck();
  }

  /** Re-enters the four-step activation wizard so an active instance can import a new license. */
  public onImportLicense(): void {
    this.wizardGenerated = false;
    this.activationKey = null;
    this.activatedEntitlement = null;
    this.wizardActive = true;
    this.cdr.markForCheck();
  }

  /** Abandons a re-import and returns to the active-license overview, leaving the license untouched. */
  public onCancelImport(): void {
    this.wizardActive = false;
    this.wizardGenerated = false;
    this.activationKey = null;
    this.activatedEntitlement = null;
    this.cdr.markForCheck();
  }

  /** Confirms the destructive removal before deleting the stored license. */
  public onDeleteLicense(): void {
    this.deleteModal.confirmDelete({
      title: 'Remove license',
      itemType: 'license',
      itemName: this.licenseName,
      warningMessage:
        'Removing the license disables all Self-Hosted features and returns this instance to the Community edition.',
      onConfirm: () => this.deleteCurrentLicense()
    });
  }

  /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  /** Applies the license fetched by the route resolver before navigation (the "precall"). */
  private applyResolvedLicense(): void {
    const resolved = this.route.snapshot.data['license'] as ResolvedLicense | undefined;

    // Defensive fallback: if the route was reached without the resolver, fetch directly.
    if (!resolved) {
      this.loadCurrentLicense();
      return;
    }

    this.loaded = true;

    if (resolved.failed || !resolved.license) {
      this.loadError = true;
      this.toast.error('The current license could not be loaded.');
      return;
    }

    this.setLicenseState(resolved.license);
    this.wizardActive = this.usesWizard(this.edition);
  }

  private loadCurrentLicense(): void {
    this.loadError = false;
    this.loaded = false;
    this.loaderService.show();

    this.licenseService.getCurrentLicense()
      .pipe(
        takeUntil(this.subscriber),
        finalize(() => this.loaderService.hide())
      )
      .subscribe({
        next: (license) => {
          this.loaded = true;
          this.setLicenseState(license);
          this.wizardActive = this.usesWizard(this.edition);
          this.cdr.markForCheck();
        },
        error: (err) => {
          this.loaded = true;
          this.loadError = true;
          this.toast.error(err?.error?.message ?? 'The current license could not be loaded.');
          this.cdr.markForCheck();
        }
      });
  }

  private deleteCurrentLicense(): void {
    this.loaderService.show();

    this.licenseService.deleteCurrentLicense()
      .pipe(
        takeUntil(this.subscriber),
        finalize(() => this.loaderService.hide())
      )
      .subscribe({
        next: () => this.onDeleteSuccess(),
        error: (err) => this.toast.error(err?.error?.message ?? 'The license could not be removed.')
      });
  }

  private onDeleteSuccess(): void {
    this.toast.success('License removed. This instance is back on the Community edition.');
    this.wizardGenerated = false;
    this.activationKey = null;
    this.activatedEntitlement = null;
    // Reseed the gating cache so gated UI (toolbox badges, etc.) locks again without a reload.
    this.premiumFeatureService.refresh();
    // Re-fetch so the edition, features and wizard state reflect the cleared license.
    this.loadCurrentLicense();
  }

  private onImportSuccess(license: CurrentLicense): void {
    this.toast.success('License imported successfully.');
    this.setLicenseState(license);
    // Seed the gating cache from the new license so gated UI unlocks immediately, no reload.
    this.premiumFeatureService.seed(license);
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
    this.rejectionTitle = this.resolveRejectionTitle(license.status);
    this.rejectionIcon = this.resolveRejectionIcon(license.status);
  }

  private onActivationKeyGenerated(key: string): void {
    const trimmed = (key ?? '').trim();

    if (!trimmed) {
      this.toast.error('The activation request response was empty.');
      return;
    }

    this.activationKey = trimmed;
    this.wizardGenerated = true;
    this.toast.success('Activation request generated.');
    this.cdr.markForCheck();
  }

  private usesWizard(edition: LicenseEdition): boolean {
    return edition === LicenseEdition.Community || edition === LicenseEdition.Expired;
  }

  /** Tier label used to identify the license in the delete confirmation prompt. */
  private get licenseName(): string {
    const type = this.entitlement?.type ?? '';
    return LICENSE_TIER_LABELS[type as LicenseTier] ?? 'Self-Hosted';
  }

  private resolveRejectionMessage(status: LicenseVerificationStatus | null): string | null {
    if (!status || status === LicenseVerificationStatus.Valid) {
      return null;
    }

    return LICENSE_STATUS_MESSAGES[status] || null;
  }

  private resolveRejectionTitle(status: LicenseVerificationStatus | null): string {
    if (!status || status === LicenseVerificationStatus.Valid) {
      return 'License warning';
    }

    return LICENSE_STATUS_TITLES[status] || 'License warning';
  }

  /** Picks an icon that reflects the failure category (time, integrity, machine binding). */
  private resolveRejectionIcon(status: LicenseVerificationStatus | null): string {
    switch (status) {
      case LicenseVerificationStatus.Expired:
        return 'fas fa-circle-exclamation';
      case LicenseVerificationStatus.NotYetValid:
        return 'fas fa-clock';
      case LicenseVerificationStatus.DecryptFailed:
      case LicenseVerificationStatus.SchemaInvalid:
        return 'fas fa-shield-halved';
      case LicenseVerificationStatus.BindingMismatch:
      case LicenseVerificationStatus.NoActivationRequest:
        return 'fas fa-ban';
      default:
        return 'fas fa-triangle-exclamation';
    }
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
}
