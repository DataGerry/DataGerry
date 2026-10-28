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

import {
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    afterRenderEffect,
    computed,
    inject,
    input,
    output,
    viewChild
} from '@angular/core';

import { CoreModule } from '../../../../core/core.module';
import {
    LICENSE_FEATURE_LABELS,
    LICENSE_TIER_FEATURES,
    LicenseFeature,
    LicenseTier
} from '../../../../settings/license-management/models/license.model';
import { OnboardingLicenseService } from '../../services/onboarding-license.service';
import { OnboardingBestPracticeService } from '../../services/onboarding-best-practice.service';
import { OnboardingDataModelService } from '../../services/onboarding-data-model.service';
import {
    OnboardingEdition,
    OnboardingImportSource,
    SetupProgressLine,
    SetupReviewRow
} from '../../models/onboarding-assistant.model';
/* ------------------------------------------------------------------------------------------------------------------ */

const PRO_FEATURES = LICENSE_TIER_FEATURES[LicenseTier.Corporate];

/** Unlocked together with IPAM. */
const IPAM_EXTRA_FEATURES = ['Port Connectivity', 'Cabling View', 'Rack View'];

@Component({
    selector: 'cmdb-onboarding-setup-step',
    templateUrl: './onboarding-setup-step.component.html',
    styleUrls: ['./onboarding-setup-step.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [CoreModule]
})
export class OnboardingSetupStepComponent {
    private readonly licenseState = inject(OnboardingLicenseService);
    private readonly bestPracticeState = inject(OnboardingBestPracticeService);
    private readonly dataModelState = inject(OnboardingDataModelService);

    public readonly isCloud = input.required<boolean>();
    public readonly version = input('');
    public readonly hostName = input('');
    public readonly edition = input.required<OnboardingEdition>();
    public readonly importSource = input<OnboardingImportSource | null>(null);
    public readonly dataModelFileName = input('');

    /** Ids of the steps the assistant currently shows. */
    public readonly availableSteps = input<string[]>([]);

    /** Empty until the user starts the setup. */
    public readonly progress = input<SetupProgressLine[]>([]);

    /** Turns the step into the finished state that leads into the tour. */
    public readonly isComplete = input(false);

    public readonly changeStep = output<string>();

    public readonly rows = computed<SetupReviewRow[]>(() => [
        this.environmentRow(),
        this.editionRow(),
        this.proFeaturesRow(),
        this.dataModelRow(),
        this.newTypesRow()
    ]);

    private readonly environmentRow = computed<SetupReviewRow>(() => ({
        id: 'environment',
        label: 'Environment',
        value: this.isCloud() ? 'DATAGERRY Cloud' : ['Self-hosted', this.hostName()].filter(Boolean).join(' · '),
        changeStep: null
    }));

    private readonly editionRow = computed<SetupReviewRow>(() => {
        const row = {
            id: 'edition',
            label: 'Edition / plan',
            changeStep: this.stepIfAvailable('edition') ?? this.stepIfAvailable('license')
        };

        if (this.isCloud()) {
            return { ...row, value: 'Cloud plan', changeStep: null };
        }

        if (this.edition() === 'community') {
            return { ...row, value: 'Community' };
        }

        return this.licenseState.isActive()
            ? { ...row, value: `Subscription ${this.licenseState.tierLabel()}` }
            : { ...row, value: 'Subscription · license not activated' };
    });

    private readonly proFeaturesRow = computed<SetupReviewRow>(() => {
        const features = this.includedFeatures().flatMap(feature => {
            const label = LICENSE_FEATURE_LABELS[feature] ?? feature;
            return feature === LicenseFeature.Ipam ? [label, ...IPAM_EXTRA_FEATURES] : [label];
        });

        return {
            id: 'pro-features',
            label: 'Pro features',
            value: features.length ? '' : 'None',
            features,
            changeStep: this.stepIfAvailable('license')
        };
    });

    /** A running line counts half, so the bar moves as soon as the setup starts. */
    public readonly progressPercent = computed(() => {
        const lines = this.progress();
        const done = lines.filter(line => line.state === 'done' || line.state === 'failed').length;
        const running = lines.filter(line => line.state === 'running').length;

        return lines.length ? ((done + running / 2) / lines.length) * 100 : 0;
    });

    public readonly hasFailed = computed(() => this.progress().some(line => line.state === 'failed'));

    public readonly setupResult = computed(() => {
        switch (this.importSource()) {
            case 'best-practice': {
                const model = this.bestPracticeState.selectedModel();
                return model ? `The ${model.title} model was applied.` : 'The best practice model was applied.';
            }
            case 'data-model':
                return 'The data model was imported.';
            default:
                return 'You start with an empty data model.';
        }
    });

    private readonly title = viewChild.required<ElementRef<HTMLElement>>('title');

    private readonly dataModelRow = computed<SetupReviewRow>(() => {
        const row = { id: 'data-model', label: 'Data model', changeStep: this.stepIfAvailable('import') };

        switch (this.importSource()) {
            case 'best-practice': {
                const model = this.bestPracticeState.selectedModel();
                return { ...row, value: model ? `Best practice: ${model.title}` : 'Best practice model' };
            }
            case 'data-model':
                return {
                    ...row,
                    value: this.dataModelState.preview()?.information?.name || this.dataModelFileName() || 'Imported data model'
                };
            default:
                return { ...row, value: 'Empty' };
        }
    });

    private readonly newTypesRow = computed<SetupReviewRow>(() => {
        let types = 0;

        switch (this.importSource()) {
            case 'best-practice':
                types = this.bestPracticeState.selectedModel()?.counts.types ?? 0;
                break;
            case 'data-model':
                types = this.dataModelState.preview()?.information?.counts?.types ?? 0;
                break;
        }

        return { id: 'new-types', label: 'New types', value: String(types), changeStep: null };
    });

    /** Cloud is always entitled; on-premise the selected edition and the active license decide. */
    private readonly includedFeatures = computed<LicenseFeature[]>(() => {
        if (this.isCloud()) {
            return PRO_FEATURES;
        }

        if (this.edition() === 'community') {
            return [];
        }

        const enabled = this.licenseState.license()?.entitlement.features ?? [];
        return PRO_FEATURES.filter(feature => enabled.includes(feature));
    });

    /** The disabled "Set up now" button loses focus while the setup runs. */
    constructor() {
        afterRenderEffect(() => {
            if (this.isComplete()) {
                this.title().nativeElement.focus();
            }
        });
    }

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onChange(stepId: string): void {
        this.changeStep.emit(stepId);
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private stepIfAvailable(stepId: string): string | null {
        return this.availableSteps().includes(stepId) ? stepId : null;
    }
}
