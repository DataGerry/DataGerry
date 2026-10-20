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
import { OnboardingEdition, SetupEditionSummary, SetupFeatureRow } from '../models/onboarding-assistant.model';
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

    public readonly editionSummary = computed<SetupEditionSummary>(() => {
        if (this.isCloud()) {
            return { icon: 'fas fa-key', label: 'Cloud plan', detail: 'Managed in the Service Portal' };
        }

        if (this.edition() === 'community') {
            return { icon: 'fas fa-heart', label: 'Community', detail: 'Free' };
        }

        return this.licenseState.isActive()
            ? { icon: 'fas fa-key', label: `Subscription ${this.licenseState.tierLabel()}`, detail: 'License active' }
            : { icon: 'fas fa-key', label: 'Subscription', detail: 'License not activated' };
    });

    public readonly proFeatures = computed<SetupFeatureRow[]>(() => {
        const included = this.includedFeatures();

        return PRO_FEATURES.map(feature => ({
            id: feature,
            label: LICENSE_FEATURE_LABELS[feature],
            isIncluded: included.includes(feature)
        }));
    });

    /** Cloud is always entitled; on-premise the selected edition and the active license decide. */
    private readonly includedFeatures = computed<LicenseFeature[]>(() => {
        if (this.isCloud()) {
            return PRO_FEATURES;
        }

        if (this.edition() === 'community') {
            return [];
        }

        return this.licenseState.license()?.entitlement.features ?? [];
    });
}
