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
import { FormControl } from '@angular/forms';
import { Router } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { finalize } from 'rxjs/operators';

import { NgbActiveModal, NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { environment } from 'src/environments/environment';
import { CoreModule } from '../../core/core.module';
import { LoaderService } from '../../core/services/loader.service';
import { CoreConfirmationModalComponent } from '../../core/components/dialog/confirmation/core-confirmation-modal.component';
import { ConnectionService } from '../../modules/connect/services/connection.service';
import { FileService } from '../../export/export.service';
import { ToastService } from '../toast/toast.service';
import { SidebarService } from '../services/sidebar.service';
import { UserSettingsDBService } from '../../management/user-settings/services/user-settings-db.service';
import { OnboardingLicenseService } from './services/onboarding-license.service';
import { OnboardingWelcomeStepComponent } from './welcome-step/onboarding-welcome-step.component';
import { OnboardingEditionStepComponent } from './edition-step/onboarding-edition-step.component';
import { OnboardingLicenseStepComponent } from './license-step/onboarding-license-step.component';
import { OnboardingPlanStepComponent } from './plan-step/onboarding-plan-step.component';
import { OnboardingImportStepComponent } from './import-step/onboarding-import-step.component';
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
        OnboardingImportStepComponent
    ],
    providers: [OnboardingLicenseService],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class OnboardingAssistantComponent implements OnInit {
    private readonly connectionService = inject(ConnectionService);
    private readonly loaderService = inject(LoaderService);
    private readonly fileService = inject(FileService);
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

    public readonly isCloud = environment.cloudMode;
    public readonly version = signal('');
    public readonly currentStepIndex = signal(0);

    public readonly selectedEdition = signal<OnboardingEdition>('community');

    public readonly selectedImportSource = signal<OnboardingImportSource | null>(null);
    public readonly dataModelFile = new FormControl<File | null>(null);

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

        steps.push({ id: 'import', title: 'Import', description: 'Data model file' });

        return steps;
    });

    public readonly currentStep = computed(() => this.steps()[this.currentStepIndex()]);
    public readonly progressPercent = computed(() => ((this.currentStepIndex() + 1) / this.steps().length) * 100);

    public readonly nextLabel = computed(() => {
        if (this.currentStepIndex() === 0) {
            return 'Get started';
        }

        return this.isLicenseStepPending() ? 'Continue without license' : 'Next';
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
            this.loadVersion();
        }
    }

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onNext(): void {
        if (this.isLicenseStepPending()) {
            this.licenseState.skip();
        }

        // Later steps run in the opener's data model flow.
        if (this.currentStepIndex() === this.steps().length - 1) {
            this.activeModal.close(true);
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

    private loadVersion(): void {
        this.loaderService.show();

        this.connectionService.getBackendInfo().pipe(
            takeUntilDestroyed(this.destroyRef),
            finalize(() => this.loaderService.hide())
        ).subscribe({
            next: info => this.version.set(info?.version ?? ''),
            error: () => this.version.set('')
        });
    }


    private resetWorkspace(): void {
        this.isResetting.set(true);
        this.loaderService.show();

        this.fileService.resetConfiguration(WORKSPACE_RESET_CONFIRMATION).pipe(
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
