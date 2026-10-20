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

import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';

import {
    LICENSE_FEATURE_LABELS,
    LICENSE_TIER_FEATURES,
    LicenseFeature,
    LicenseTier
} from '../../../settings/license-management/models/license.model';
import { OnboardingLicenseService } from '../services/onboarding-license.service';
import { OnboardingEdition, SetupSummaryItem } from '../models/onboarding-assistant.model';
/* ------------------------------------------------------------------------------------------------------------------ */

const PRO_FEATURES = LICENSE_TIER_FEATURES[LicenseTier.Corporate];

@Component({
    selector: 'cmdb-onboarding-setup-step',
    templateUrl: './onboarding-setup-step.component.html',
    styleUrls: ['./onboarding-setup-step.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class OnboardingSetupStepComponent {
    private readonly licenseState = inject(OnboardingLicenseService);

    public readonly isCloud = input.required<boolean>();
    public readonly version = input('');
    public readonly edition = input.required<OnboardingEdition>();

    public readonly summary = computed<SetupSummaryItem[]>(() => [
        this.environmentSummary(),
        this.editionSummary(),
        this.proFeaturesSummary()
    ]);

    private readonly environmentSummary = computed<SetupSummaryItem>(() => ({
        id: 'environment',
        icon: this.isCloud() ? 'fas fa-cloud' : 'fas fa-server',
        title: 'Environment',
        value: this.isCloud() ? 'DATAGERRY Cloud' : 'Self-hosted',
        detail: this.version() ? `Version ${this.version()}` : ''
    }));

    private readonly editionSummary = computed<SetupSummaryItem>(() => {
        const item = { id: 'edition', icon: 'fas fa-key', title: 'Edition' };

        if (this.isCloud()) {
            return { ...item, value: 'Cloud plan', detail: 'Managed in the Service Portal' };
        }

        if (this.edition() === 'community') {
            return { ...item, icon: 'fas fa-heart', value: 'Community', detail: 'Free' };
        }

        return this.licenseState.isActive()
            ? { ...item, value: `Subscription ${this.licenseState.tierLabel()}`, detail: 'License active' }
            : { ...item, value: 'Subscription', detail: 'License not activated' };
    });

    private readonly proFeaturesSummary = computed<SetupSummaryItem>(() => {
        const included = this.includedFeatures();
        const item = { id: 'pro-features', icon: 'fas fa-gem', title: 'Pro features' };

        if (!included.length) {
            return { ...item, value: 'None included', detail: '' };
        }

        if (included.length === PRO_FEATURES.length) {
            return { ...item, value: 'All included', detail: '' };
        }

        return {
            ...item,
            value: `${included.length} of ${PRO_FEATURES.length} included`,
            detail: included.map(feature => LICENSE_FEATURE_LABELS[feature]).join(', ')
        };
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
}
