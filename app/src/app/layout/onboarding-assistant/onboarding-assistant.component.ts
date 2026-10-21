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
import { finalize } from 'rxjs/operators';

import { NgbActiveModal, NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { environment } from 'src/environments/environment';
import { CoreModule } from '../../core/core.module';
import { LoaderService } from '../../core/services/loader.service';
import { CoreConfirmationModalComponent } from '../../core/components/dialog/confirmation/core-confirmation-modal.component';
import { SystemService } from '../../settings/system/system.service';
import { DeploymentInformation } from '../../settings/system/models/deployment-information.model';
import { ImportService } from '../../modules/import/services/import.service';
import { ToastService } from '../toast/toast.service';
import { SidebarService } from '../services/sidebar.service';
import { UserSettingsDBService } from '../../management/user-settings/services/user-settings-db.service';
import { OnboardingLicenseService } from './services/onboarding-license.service';
import { OnboardingWorkspaceService } from './services/onboarding-workspace.service';
import { OnboardingWelcomeStepComponent } from './components/welcome-step/onboarding-welcome-step.component';
import { OnboardingEditionStepComponent } from './components/edition-step/onboarding-edition-step.component';
import { OnboardingLicenseStepComponent } from './components/license-step/onboarding-license-step.component';
import { OnboardingPlanStepComponent } from './components/plan-step/onboarding-plan-step.component';
import { OnboardingImportStepComponent } from './components/import-step/onboarding-import-step.component';
import { OnboardingSetupStepComponent } from './components/setup-step/onboarding-setup-step.component';
import { OnboardingCompleteStepComponent } from './components/complete-step/onboarding-complete-step.component';
import {
    OnboardingEdition,
    OnboardingImportSource,
    OnboardingStep,
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
        OnboardingPlanStepComponent,
        OnboardingImportStepComponent,
        OnboardingSetupStepComponent,
        OnboardingCompleteStepComponent
    ],
    providers: [OnboardingLicenseService],
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

    public readonly activeModal = inject(NgbActiveModal);
    public readonly isLoading$ = this.loaderService.isLoading$;

    /** Set to false by the opener when the data model already exists. */
    public readonly isUsable = signal(true);

    /** Set by the opener; the reset route accepts the administrator account only. */
    public readonly canReset = signal(false);

    public readonly isResetting = signal(false);
    public readonly isImporting = signal(false);
    public readonly isImportComplete = signal(false);

    public readonly isCloud = environment.cloudMode;
    public readonly deployment = signal<DeploymentInformation | null>(null);
    public readonly version = computed(() => this.deployment()?.version ?? '');
    public readonly currentStepIndex = signal(0);

    public readonly selectedEdition = signal<OnboardingEdition>('community');

    public readonly selectedImportSource = signal<OnboardingImportSource | null>('empty');
    public readonly dataModelFile = new FormControl<File | null>(null);
    private readonly dataModelFileValue = toSignal(this.dataModelFile.valueChanges, {
        initialValue: this.dataModelFile.value
    });

    public readonly steps = computed<OnboardingStep[]>(() => {
        const steps: OnboardingStep[] = [{
            id: 'welcome',
            title: 'Welcome',
            description: this.isCloud ? 'DATAGERRY Cloud' : 'Self-hosted'
        }];

        if (this.isCloud) {
            steps.push({ id: 'plan', title: 'Your plan', description: 'Trial or subscription' });
        } else {
            steps.push({ id: 'edition', title: 'Edition', description: 'Community or Subscription' });

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
    public readonly progressPercent = computed(() =>
        this.isImportComplete() ? 100 : ((this.currentStepIndex() + 1) / this.steps().length) * 100
    );

    public readonly nextLabel = computed(() => {
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

    public readonly isEmptyDataModel = computed(() => this.selectedImportSource() === 'empty');

    private readonly isImportSourceReady = computed(() =>
        this.isEmptyDataModel() || (this.selectedImportSource() === 'data-model' && !!this.dataModelFileValue())
    );

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
        }
    }

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onNext(): void {
        if (this.isLicenseStepPending()) {
            this.licenseState.skip();
        }

        if (this.currentStep().id === 'setup' && this.isEmptyDataModel()) {
            this.recordEmptyDataModel();
            return;
        }

        if (this.currentStep().id === 'setup') {
            this.importDataModel();
            return;
        }

        this.currentStepIndex.update(index => index + 1);
    }


    public onSecondaryAction(): void {
        if (this.currentStepIndex() === 0) {
            this.onSetUpLater();
            return;
        }

        this.currentStepIndex.update(index => index - 1);
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
        const confirmation = this.modalService.open(CoreConfirmationModalComponent, {
            centered: true,
            backdrop: 'static',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop',
            ariaLabelledBy: 'confirmation-title',
            ariaDescribedBy: 'confirmation-message'
        });

        confirmation.componentInstance.title = 'Reset workspace';
        confirmation.componentInstance.message =
            'All types, categories, objects, relations and the data that depends on them are deleted. '
            + 'Users and groups are kept.';
        confirmation.componentInstance.warningMessage = 'This cannot be undone.';
        confirmation.componentInstance.confirmationText = WORKSPACE_RESET_CONFIRMATION;
        confirmation.componentInstance.confirmButtonText = 'Reset workspace';
        confirmation.componentInstance.confirmButtonClass = 'btn-danger';

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


    private importDataModel(): void {
        const file = this.dataModelFile.value;

        if (!file || this.isImporting()) {
            return;
        }

        this.isImporting.set(true);
        this.loaderService.show();

        this.importService.importDataModel(file).pipe(
            takeUntilDestroyed(this.destroyRef),
            finalize(() => {
                this.isImporting.set(false);
                this.loaderService.hide();
            })
        ).subscribe({
            next: () => this.completeImport(),
            error: (error: unknown) => this.toastService.error(this.resolveImportError(error))
        });
    }


    private recordEmptyDataModel(): void {
        if (this.isImporting()) {
            return;
        }

        this.isImporting.set(true);
        this.loaderService.show();

        this.workspaceService.recordDecision('empty_data_model').pipe(
            takeUntilDestroyed(this.destroyRef),
            finalize(() => {
                this.isImporting.set(false);
                this.loaderService.hide();
            })
        ).subscribe({
            next: () => this.isImportComplete.set(true),
            error: () => this.toastService.error('The empty data model could not be set up.')
        });
    }


    /** The import also cleared every user's settings, so the cached copies are synced away. */
    private completeImport(): void {
        this.userSettingsDBService.syncSettings();
        this.sidebarService.loadCategoryTree();
        this.toastService.success('The data model was imported.');

        this.router.navigate(['/']).finally(() => this.isImportComplete.set(true));
    }


    /** A 400 names the file's problems for the user; any other failure stays generic. */
    private resolveImportError(error: unknown): string {
        if (error instanceof HttpErrorResponse && error.status === 400 && error.error?.message) {
            return error.error.message;
        }

        return 'The data model could not be imported.';
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
