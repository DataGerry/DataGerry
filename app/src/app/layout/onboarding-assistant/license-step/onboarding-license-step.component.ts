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

import { DOCUMENT, DatePipe, formatDate } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    Injector,
    LOCALE_ID,
    OnInit,
    afterNextRender,
    computed,
    effect,
    inject,
    linkedSignal,
    viewChildren
} from '@angular/core';

import { CoreModule } from '../../../core/core.module';
import { formatFileSize } from '../../../core/utils/file-size.util';
import { PREMIUM_FEATURE_CONTENT } from '../../../settings/license-management/premium-feature/premium-feature.config';
import {
    ACTIVATION_REQUEST_FILENAME,
    LICENSE_FEATURE_LABELS,
    LICENSE_TIER_FEATURES,
    LicenseTier,
    SERVICE_PORTAL_LICENSE_URL
} from '../../../settings/license-management/models/license.model';
import {
    ACTIVATION_SUB_STEP_TITLES,
    ActivationPhase,
    ActivationSubStep,
    ActivationSubStepState,
    LicenseFeatureRow
} from '../models/onboarding-license.model';
import { OnboardingLicenseService } from '../services/onboarding-license.service';
/* ------------------------------------------------------------------------------------------------------------------ */

const SUB_STEP_ORDER = [ActivationPhase.Request, ActivationPhase.Portal, ActivationPhase.Import];

@Component({
    selector: 'cmdb-onboarding-license-step',
    templateUrl: './onboarding-license-step.component.html',
    styleUrls: ['./onboarding-license-step.component.scss'],
    imports: [DatePipe, CoreModule],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class OnboardingLicenseStepComponent implements OnInit {
    public readonly licenseState = inject(OnboardingLicenseService);
    private readonly injector = inject(Injector);
    private readonly document = inject(DOCUMENT);
    private readonly locale = inject(LOCALE_ID);

    private readonly stepTitles = viewChildren<ElementRef<HTMLElement>>('stepTitle');

    public readonly Phase = ActivationPhase;
    public readonly requestFileName = ACTIVATION_REQUEST_FILENAME;
    public readonly portalUrl = SERVICE_PORTAL_LICENSE_URL;

    public readonly formatFileSize = formatFileSize;

    /** The sub-step the user works on; an active license makes it the import result. */
    private readonly focusStep = computed(() =>
        this.licenseState.isActive() ? ActivationPhase.Import : this.licenseState.phase()
    );

    /** Completed sub-steps the user reopened; cleared whenever the flow moves on. */
    private readonly reopenedSteps = linkedSignal<ActivationPhase, ReadonlySet<ActivationPhase>>({
        source: this.focusStep,
        computation: () => new Set()
    });

    public readonly subSteps = computed<ActivationSubStep[]>(() => {
        const focusStep = this.focusStep();
        const reopened = this.reopenedSteps();

        return SUB_STEP_ORDER.map(phase => {
            const state = this.stateOf(phase);
            const isCollapsible = state === 'done' && phase !== focusStep && this.hasDetails(phase);

            return {
                phase,
                title: ACTIVATION_SUB_STEP_TITLES[phase],
                state,
                isOpen: phase === focusStep || (isCollapsible && reopened.has(phase)),
                isCollapsible,
                hasFramedPanel: this.hasFramedPanel(phase),
                summary: this.summaryOf(phase, state)
            };
        });
    });

    public readonly maskedLicenseId = computed(() => {
        const id = this.licenseState.license()?.entitlement.licenseId ?? '';
        return id ? `•••• ${id.replace(/-/g, '').slice(-4)}` : '–';
    });

    public readonly features = computed<LicenseFeatureRow[]>(() => {
        const enabled = this.licenseState.license()?.entitlement.features ?? [];

        return LICENSE_TIER_FEATURES[LicenseTier.Corporate]
            .filter(feature => enabled.includes(feature))
            .map(feature => ({
                id: feature,
                label: LICENSE_FEATURE_LABELS[feature],
                description: PREMIUM_FEATURE_CONTENT[feature]?.description ?? ''
            }));
    });

    private hasInteracted = false;

    /** Actions remove or collapse the control that triggered them, so lost focus moves to the current sub-step. */
    constructor() {
        effect(() => {
            this.focusStep();
            this.licenseState.activationRequest();
            this.licenseState.isImporting();
            this.licenseState.importError();

            if (this.hasInteracted) {
                afterNextRender(() => this.restoreLostFocus(), { injector: this.injector });
            }
        });
    }

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.licenseState.loadCurrentLicense();
    }

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onToggleStep(phase: ActivationPhase): void {
        this.reopenedSteps.update(reopened => {
            const next = new Set(reopened);

            if (!next.delete(phase)) {
                next.add(phase);
            }

            return next;
        });
    }


    public onCreateRequest(): void {
        this.hasInteracted = true;
        this.licenseState.createActivationRequest();
    }


    public onContinueWithExistingRequest(): void {
        this.hasInteracted = true;
        this.licenseState.continueWithExistingRequest();
    }


    public onDownloadRequest(): void {
        this.licenseState.downloadActivationRequest();
    }


    public onLicenseFileReceived(): void {
        this.hasInteracted = true;
        this.licenseState.confirmLicenseFileReceived();
    }


    public onLicenseFileSelected(file: File): void {
        this.hasInteracted = true;
        this.licenseState.importLicense(file);
    }


    public onLicenseFileCleared(): void {
        this.licenseState.clearImportError();
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private stateOf(phase: ActivationPhase): ActivationSubStepState {
        if (this.licenseState.isActive() || this.licenseState.phase() > phase) {
            return 'done';
        }

        return this.licenseState.phase() === phase ? 'current' : 'idle';
    }


    /** An instance that was already licensed never created a request, so its first sub-step has nothing to show. */
    private hasDetails(phase: ActivationPhase): boolean {
        return phase !== ActivationPhase.Request
            || !!this.licenseState.activationRequest()
            || !this.licenseState.isActive();
    }


    /** File, license and drop zone content is already a card, so only text and actions get a panel. */
    private hasFramedPanel(phase: ActivationPhase): boolean {
        return phase === ActivationPhase.Portal
            || (phase === ActivationPhase.Request && !this.licenseState.activationRequest());
    }


    private summaryOf(phase: ActivationPhase, state: ActivationSubStepState): string {
        if (state === 'idle') {
            return `Available after step ${phase - 1}`;
        }

        const passedByUser = this.licenseState.phase() > phase;

        switch (phase) {
            case ActivationPhase.Request: {
                const request = this.licenseState.activationRequest();

                if (request) {
                    return `${this.requestFileName} · created at ${formatDate(request.createdAt, 'shortTime', this.locale)}`;
                }

                return passedByUser ? 'Using an existing request' : '';
            }
            case ActivationPhase.Portal:
                return passedByUser ? 'License file received' : '';
            default:
                return this.licenseState.isActive() ? `Subscription ${this.licenseState.tierLabel()} active` : '';
        }
    }


    private restoreLostFocus(): void {
        const activeElement = this.document.activeElement;

        if (activeElement && activeElement !== this.document.body && !activeElement.closest('[inert]')) {
            return;
        }

        this.stepTitles()[this.focusStep() - 1]?.nativeElement.focus();
    }

}
