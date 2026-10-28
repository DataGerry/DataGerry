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

import { AsyncPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { FormControl } from '@angular/forms';
import { Router } from '@angular/router';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { Observable, from } from 'rxjs';
import { finalize, switchMap, take } from 'rxjs/operators';

import { NgbActiveModal, NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { environment } from 'src/environments/environment';
import { CoreModule } from '../../core/core.module';
import { LoaderService } from '../../core/services/loader.service';
import { SystemService } from '../../settings/system/system.service';
import { DeploymentInformation } from '../../settings/system/models/deployment-information.model';
import { ImportService } from '../../modules/import/services/import.service';
import { ToastService } from '../toast/toast.service';
import { SidebarService } from '../services/sidebar.service';
import { UserSettingsDBService } from '../../management/user-settings/services/user-settings-db.service';
import { PremiumFeatureService } from '../../settings/license-management/premium-feature/premium-feature.service';
import { COMMUNITY_TIER } from '../../settings/license-management/models/license.model';
import { OnboardingLicenseService } from './services/onboarding-license.service';
import { OnboardingWorkspaceService } from './services/onboarding-workspace.service';
import { OnboardingBestPracticeService } from './services/onboarding-best-practice.service';
import { OnboardingDataModelService } from './services/onboarding-data-model.service';
import { OnboardingWelcomeStepComponent } from './components/welcome-step/onboarding-welcome-step.component';
import { OnboardingEditionStepComponent } from './components/edition-step/onboarding-edition-step.component';
import { OnboardingLicenseStepComponent } from './components/license-step/onboarding-license-step.component';
import { OnboardingImportStepComponent } from './components/import-step/onboarding-import-step.component';
import { OnboardingSetupStepComponent } from './components/setup-step/onboarding-setup-step.component';
import { OnboardingResetConfirmationModalComponent } from './components/reset-confirmation-modal/onboarding-reset-confirmation-modal.component';
import {
    OnboardingEdition,
    OnboardingImportSource,
    OnboardingStep,
    SetupProgressLabels,
    SetupProgressLine,
    SetupProgressState,
    WORKSPACE_RESET_CONFIRMATION
} from './models/onboarding-assistant.model';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-onboarding-assistant',
    templateUrl: './onboarding-assistant.component.html',
    styleUrls: ['./onboarding-assistant.component.scss'],
    imports: [
        AsyncPipe,
        CoreModule,
        OnboardingWelcomeStepComponent,
        OnboardingEditionStepComponent,
        OnboardingLicenseStepComponent,
        OnboardingImportStepComponent,
        OnboardingSetupStepComponent
    ],
    providers: [OnboardingLicenseService, OnboardingBestPracticeService, OnboardingDataModelService],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class OnboardingAssistantComponent implements OnInit {
    private readonly systemService = inject(SystemService);
    private readonly loaderService = inject(LoaderService);
    private readonly importService = inject(ImportService);
    private readonly workspaceService = inject(OnboardingWorkspaceService);
    private readonly toastService = inject(ToastService);
    private readonly sidebarService = inject(SidebarService);
    private readonly userSettingsDBService = inject(UserSettingsDBService);
    private readonly router = inject(Router);
    private readonly modalService = inject(NgbModal);
    private readonly destroyRef = inject(DestroyRef);
    private readonly licenseState = inject(OnboardingLicenseService);
    private readonly bestPracticeState = inject(OnboardingBestPracticeService);
    private readonly dataModelState = inject(OnboardingDataModelService);
    private readonly premiumFeatureService = inject(PremiumFeatureService);

    public readonly activeModal = inject(NgbActiveModal);
    public readonly isLoading$ = this.loaderService.isLoading$;

    /** Set to false by the opener when the data model already exists. */
    public readonly isUsable = signal(true);

    /** Set by the opener; the reset route needs the right `base.*`. */
    public readonly canReset = signal(false);

    /** Set by the opener from the offer; importing a data model or a best-practice model needs the right `base.*`. */
    public readonly canImport = signal(false);

    public readonly isResetting = signal(false);
    public readonly isImporting = signal(false);
    public readonly isImportComplete = signal(false);

    public readonly isCloud = environment.cloudMode;
    public readonly deployment = signal<DeploymentInformation | null>(null);
    public readonly version = computed(() => this.deployment()?.version ?? '');
    public readonly currentStepIndex = signal(0);

    public readonly selectedEdition = signal<OnboardingEdition>('community');

    /** Filled while "Set up now" runs; shown on the setup step. */
    public readonly setupProgress = signal<SetupProgressLine[]>([]);

    /** Fixed when the assistant opens, so importing a license on the way does not shift the steps. */
    private readonly hasExistingLicense = signal(false);

    public readonly selectedImportSource = signal<OnboardingImportSource | null>('empty');
    public readonly dataModelFile = new FormControl<File | null>(null);
    public readonly dataModelFileValue = toSignal(this.dataModelFile.valueChanges, {
        initialValue: this.dataModelFile.value
    });

    public readonly steps = computed<OnboardingStep[]>(() => {
        const steps: OnboardingStep[] = [{
            id: 'welcome',
            title: 'Welcome',
            description: this.isCloud ? 'DATAGERRY Cloud' : 'Self-hosted'
        }];

        if (!this.isCloud) {
            if (!this.hasExistingLicense()) {
                steps.push({ id: 'edition', title: 'Edition', description: 'Community or Subscription' });
            }

            if (this.selectedEdition() === 'subscription') {
                steps.push({ id: 'license', title: 'Activate license', description: this.licenseStepDescription() });
            }
        }

        steps.push(
            { id: 'import', title: 'Import', description: 'Data model file' },
            { id: 'setup', title: 'Setup', description: 'Environment, edition, pro features' }
        );

        return steps;
    });

    public readonly currentStep = computed(() => this.steps()[this.currentStepIndex()]);
    public readonly stepIds = computed(() => this.steps().map(step => step.id));
    public readonly progressPercent = computed(() =>
        this.isImportComplete() ? 100 : ((this.currentStepIndex() + 1) / this.steps().length) * 100
    );

    public readonly nextLabel = computed(() => {
        if (this.isImportComplete()) {
            return 'Start tour';
        }

        if (this.currentStepIndex() === 0) {
            return 'Get started';
        }

        if (this.currentStep().id === 'setup') {
            return 'Set up now';
        }

        return this.isLicenseStepPending() ? 'Continue without license' : 'Next';
    });

    public readonly isNextDisabled = computed(() =>
        this.isImporting() || (this.currentStep().id === 'import' && !this.isImportSourceReady())
    );

    private readonly isImportSourceReady = computed(() => {
        switch (this.selectedImportSource()) {
            case 'empty':
                return true;
            case 'data-model':
                return this.canImport() && !!this.dataModelFileValue() && this.dataModelState.isImportable();
            case 'best-practice':
                return this.canImport() && !!this.bestPracticeState.selectedModel();
            default:
                return false;
        }
    });

    public readonly isLicenseStepPending = computed(() =>
        this.currentStep().id === 'license' && !this.licenseState.isActive()
    );

    private readonly licenseStepDescription = computed(() => {
        switch (this.licenseState.status()) {
            case 'active':
                return `${this.licenseState.tierLabel()} active`;
            case 'skipped':
                return 'Later';
            default:
                return 'Request and license file';
        }
    });

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        if (this.isUsable()) {
            this.loadDeployment();
            this.previewSelectedDataModel();

            if (!this.isCloud) {
                this.detectExistingLicense();
            }
        }
    }

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onNext(): void {
        if (this.isImportComplete()) {
            this.onStartTour();
            return;
        }

        if (this.isLicenseStepPending()) {
            this.licenseState.skip();
        }

        if (this.currentStep().id === 'setup') {
            this.setUpDataModel();
            return;
        }

        this.currentStepIndex.update(index => index + 1);
    }


    public onSecondaryAction(): void {
        if (this.currentStepIndex() === 0) {
            this.onSetUpLater();
            return;
        }

        this.setupProgress.set([]);
        this.currentStepIndex.update(index => index - 1);
    }


    public onChangeStep(stepId: string): void {
        const index = this.stepIds().indexOf(stepId);

        if (index >= 0 && !this.isImporting()) {
            this.setupProgress.set([]);
            this.currentStepIndex.set(index);
        }
    }


    public onEditionSelected(edition: OnboardingEdition): void {
        this.selectedEdition.set(edition);

        if (edition === 'community') {
            this.licenseState.clearSkip();
        }
    }


    public onSetUpLater(): void {
        this.activeModal.dismiss(false);
    }


    public onClose(): void {
        if (this.isImportComplete()) {
            this.activeModal.close('imported');
            return;
        }

        this.onSetUpLater();
    }


    /** The opener starts the tour once the modal is gone, so its focus restore cannot pull focus out of the tour. */
    public onStartTour(): void {
        this.activeModal.close('tour');
    }


    public onStartReset(): void {
        const confirmation = this.modalService.open(OnboardingResetConfirmationModalComponent, {
            centered: true,
            backdrop: 'static',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop',
            ariaLabelledBy: 'reset-confirmation-title',
            ariaDescribedBy: 'reset-confirmation-message'
        });

        confirmation.componentInstance.title = 'Reset workspace';
        confirmation.componentInstance.message =
            'All types, categories, objects, relations and the data that depends on them are deleted. '
            + 'Users and groups are kept.';
        confirmation.componentInstance.warningMessage = 'This cannot be undone.';
        confirmation.componentInstance.confirmationText = WORKSPACE_RESET_CONFIRMATION;
        confirmation.componentInstance.confirmButtonText = 'Reset workspace';
        confirmation.componentInstance.confirmTone = 'danger';

        confirmation.result.then((result: unknown) => {
            if (result === 'confirmed') {
                this.resetWorkspace();
            }
        }, () => { });
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private loadDeployment(): void {
        this.loaderService.show();

        this.systemService.getDeploymentInformation().pipe(
            takeUntilDestroyed(this.destroyRef),
            finalize(() => this.loaderService.hide())
        ).subscribe({
            next: deployment => this.deployment.set(deployment ?? null),
            error: () => this.deployment.set(null)
        });
    }


    private previewSelectedDataModel(): void {
        this.dataModelFile.valueChanges.pipe(
            takeUntilDestroyed(this.destroyRef)
        ).subscribe(file => this.dataModelState.loadPreview(file));
    }


    /** Uses the entitlements, which unlike the license detail need no license right. */
    private detectExistingLicense(): void {
        this.loaderService.show();

        this.premiumFeatureService.currentEdition$().pipe(
            take(1),
            takeUntilDestroyed(this.destroyRef),
            finalize(() => this.loaderService.hide())
        ).subscribe(tier => {
            if (tier === COMMUNITY_TIER) {
                return;
            }

            this.hasExistingLicense.set(true);
            this.selectedEdition.set('subscription');
            this.licenseState.loadCurrentLicense();
        });
    }


    private setUpDataModel(): void {
        switch (this.selectedImportSource()) {
            case 'empty':
                this.recordEmptyDataModel();
                break;
            case 'data-model':
                this.importDataModel();
                break;
            case 'best-practice':
                this.applyBestPracticeModel();
                break;
        }
    }


    private importDataModel(): void {
        const file = this.dataModelFile.value;

        if (!file) {
            return;
        }

        this.runSetup(() => this.importService.importDataModel(file), {
            running: 'Importing the data model',
            done: 'Data model imported',
            failed: 'The data model could not be imported.'
        }, () => this.completeImport('The data model was imported.'));
    }


    private applyBestPracticeModel(): void {
        const model = this.bestPracticeState.selectedModel();

        if (!model) {
            return;
        }

        this.runSetup(() => this.workspaceService.applyBestPracticeModel(model.model_id), {
            running: `Applying the ${model.title} model`,
            done: `${model.title} model applied`,
            failed: 'The best practice model could not be applied.'
        }, () => this.completeImport(`The ${model.title} model was applied.`));
    }


    private recordEmptyDataModel(): void {
        this.runSetup(() => this.workspaceService.recordDecision('empty_data_model'), {
            running: 'Preparing the empty data model',
            done: 'Empty data model prepared',
            failed: 'The empty data model could not be set up.'
        }, () => Promise.resolve());
    }


    /** The progress on the setup step stands in for the loading popup, which would cover it. */
    private runSetup(request: () => Observable<unknown>, labels: SetupProgressLabels,
        afterSetup: () => Promise<unknown>): void {
        if (this.isImporting()) {
            return;
        }

        this.isImporting.set(true);
        this.setSetupProgress(labels.running, 'running', 'pending');

        request().pipe(
            switchMap(() => {
                this.setSetupProgress(labels.done, 'done', 'done');
                return from(afterSetup());
            }),
            takeUntilDestroyed(this.destroyRef)
        ).subscribe({
            next: () => {
                this.isImporting.set(false);
                this.isImportComplete.set(true);
            },
            error: (error: unknown) => {
                this.isImporting.set(false);
                this.setSetupProgress(labels.failed, 'failed', 'pending');
                this.toastService.error(this.resolveImportError(error, labels.failed));
            }
        });
    }


    private setSetupProgress(label: string, state: SetupProgressState, completeState: SetupProgressState): void {
        this.setupProgress.set([
            { id: 'data-model', label, state },
            { id: 'complete', label: 'Setup complete', state: completeState }
        ]);
    }


    /** The import also cleared every user's settings, so the cached copies are synced away. */
    private completeImport(successMessage: string): Promise<unknown> {
        this.userSettingsDBService.syncSettings();
        this.sidebarService.loadCategoryTree();
        this.toastService.success(successMessage);

        // The data model is in place either way, so a failed navigation must not read as a failed setup.
        return this.router.navigate(['/']).catch(() => false);
    }


    /** A 400 names the file's problems for the user; any other failure stays generic. */
    private resolveImportError(error: unknown, fallback: string): string {
        if (error instanceof HttpErrorResponse && error.status === 400 && error.error?.message) {
            return error.error.message;
        }

        return fallback;
    }


    private resetWorkspace(): void {
        this.isResetting.set(true);
        this.loaderService.show();

        this.workspaceService.resetConfiguration(WORKSPACE_RESET_CONFIRMATION).pipe(
            takeUntilDestroyed(this.destroyRef),
            finalize(() => {
                this.isResetting.set(false);
                this.loaderService.hide();
            })
        ).subscribe({
            next: () => this.completeReset(),
            error: () => this.toastService.error('The workspace could not be reset.')
        });
    }


    /** The reset also cleared every user's settings, so the cached copies are synced away. */
    private completeReset(): void {
        this.userSettingsDBService.syncSettings();
        this.sidebarService.loadCategoryTree();
        this.toastService.success('The workspace was reset.');

        this.router.navigate(['/']).finally(() => this.activeModal.close('reset'));
    }
}
