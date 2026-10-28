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

import { NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';

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
import { toCountItems } from '../../utils/onboarding-best-practice.util';
import {
    DATA_MODEL_COUNT_LABELS,
    OnboardingEdition,
    OnboardingImportSource,
    SetupCountItem,
    SetupFeatureItem,
    SetupSummaryItem
} from '../../models/onboarding-assistant.model';
/* ------------------------------------------------------------------------------------------------------------------ */

const PRO_FEATURES = LICENSE_TIER_FEATURES[LicenseTier.Corporate];

/** Shown next to IPAM; ports, cabling and the rack view are unlocked by the IPAM license. */
const IPAM_FEATURE_ITEMS = [
    { id: 'port-connectivity', label: 'Port Connectivity' },
    { id: 'cabling-view', label: 'Cabling View' },
    { id: 'rack-view', label: 'Rack View' }
];

@Component({
    selector: 'cmdb-onboarding-setup-step',
    templateUrl: './onboarding-setup-step.component.html',
    styleUrls: ['./onboarding-setup-step.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [NgTemplateOutlet, CoreModule]
})
export class OnboardingSetupStepComponent {
    private readonly licenseState = inject(OnboardingLicenseService);
    private readonly bestPracticeState = inject(OnboardingBestPracticeService);
    private readonly dataModelState = inject(OnboardingDataModelService);

    public readonly isCloud = input.required<boolean>();
    public readonly version = input('');
    public readonly edition = input.required<OnboardingEdition>();
    public readonly importSource = input<OnboardingImportSource | null>(null);
    public readonly dataModelFileName = input('');

    /** Ids of the steps the assistant currently shows. */
    public readonly availableSteps = input<string[]>([]);

    public readonly changeStep = output<string>();

    public readonly summary = computed<SetupSummaryItem[]>(() => [
        this.environmentSummary(),
        this.editionSummary()
    ]);

    public readonly dataModelSummary = computed<SetupSummaryItem>(() => {
        const item = { id: 'data-model', title: 'Data model', changeStep: this.stepIfAvailable('import') };

        switch (this.importSource()) {
            case 'best-practice': {
                const model = this.bestPracticeState.selectedModel();
                return {
                    ...item,
                    icon: 'fas fa-sitemap',
                    value: model?.title ?? 'Best practice model',
                    detail: model?.summary ?? ''
                };
            }
            case 'data-model': {
                const information = this.dataModelState.preview()?.information;
                return {
                    ...item,
                    icon: 'fas fa-file-import',
                    value: information?.name || 'Imported data model',
                    detail: this.dataModelFileName()
                };
            }
            default:
                return {
                    ...item,
                    icon: 'fas fa-file',
                    value: 'Empty data model',
                    detail: 'You create your own types and categories after setup.'
                };
        }
    });

    public readonly dataModelCounts = computed<SetupCountItem[]>(() => {
        switch (this.importSource()) {
            case 'best-practice': {
                const counts = this.bestPracticeState.selectedModel()?.counts;
                return counts ? toCountItems(counts) : [];
            }
            case 'data-model': {
                const counts = this.dataModelState.preview()?.information?.counts;
                return counts ? DATA_MODEL_COUNT_LABELS.map(item => ({ ...item, value: counts[item.id] ?? 0 })) : [];
            }
            default:
                return [];
        }
    });

    public readonly proFeatures = computed<SetupFeatureItem[]>(() => {
        const included = this.includedFeatures();

        return PRO_FEATURES.flatMap(feature => {
            const item = { id: feature, label: LICENSE_FEATURE_LABELS[feature], included: included.includes(feature) };
            const extras = feature === LicenseFeature.Ipam
                ? IPAM_FEATURE_ITEMS.map(extra => ({ ...extra, included: item.included }))
                : [];

            return [item, ...extras];
        });
    });

    public readonly proFeaturesSummary = computed<SetupSummaryItem>(() => {
        const features = this.proFeatures();
        const count = features.filter(feature => feature.included).length;
        let value = `${count} of ${features.length} included`;

        if (!count) {
            value = 'None included';
        } else if (count === features.length) {
            value = 'All included';
        }

        return {
            id: 'pro-features',
            icon: 'fas fa-gem',
            title: 'Pro features',
            value,
            detail: '',
            changeStep: this.stepIfAvailable('license')
        };
    });

    private readonly environmentSummary = computed<SetupSummaryItem>(() => ({
        id: 'environment',
        icon: this.isCloud() ? 'fas fa-cloud' : 'fas fa-server',
        title: 'Environment',
        value: this.isCloud() ? 'DATAGERRY Cloud' : 'Self-hosted',
        detail: this.version() ? `Version ${this.version()}` : '',
        changeStep: null
    }));

    private readonly editionSummary = computed<SetupSummaryItem>(() => {
        const item = {
            id: 'edition',
            icon: 'fas fa-key',
            title: 'Edition',
            changeStep: this.stepIfAvailable('edition') ?? this.stepIfAvailable('license')
        };

        if (this.isCloud()) {
            return { ...item, value: 'Cloud plan', detail: 'Managed in the Service Portal', changeStep: null };
        }

        if (this.edition() === 'community') {
            return { ...item, icon: 'fas fa-heart', value: 'Community', detail: 'Free' };
        }

        return this.licenseState.isActive()
            ? { ...item, value: `Subscription ${this.licenseState.tierLabel()}`, detail: 'License active' }
            : { ...item, value: 'Subscription', detail: 'License not activated' };
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

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onChange(stepId: string): void {
        this.changeStep.emit(stepId);
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private stepIfAvailable(stepId: string): string | null {
        return this.availableSteps().includes(stepId) ? stepId : null;
    }
}
