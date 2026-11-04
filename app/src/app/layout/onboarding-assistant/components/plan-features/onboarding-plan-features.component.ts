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

import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import {
    LICENSE_TIER_FEATURES,
    LICENSE_TIER_FILTER_ORDER,
    LICENSE_TIER_LABELS,
    LicenseFeature
} from '../../../../settings/license-management/models/license.model';
import { PLAN_FEATURES } from '../../models/onboarding-license.model';
/* ------------------------------------------------------------------------------------------------------------------ */

let nextId = 0;

@Component({
    selector: 'cmdb-onboarding-plan-features',
    templateUrl: './onboarding-plan-features.component.html',
    styleUrls: ['./onboarding-plan-features.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class OnboardingPlanFeaturesComponent {
    public readonly enabledFeatures = input<LicenseFeature[]>([]);

    public readonly labelId = `plan-features-label-${nextId++}`;

    public readonly features = computed(() => {
        const enabled = this.enabledFeatures();

        return PLAN_FEATURES.map(item => ({
            ...item,
            isIncluded: enabled.includes(item.feature),
            requiredPlan: this.requiredPlanOf(item.feature)
        }));
    });

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private requiredPlanOf(feature: LicenseFeature): string {
        const tier = LICENSE_TIER_FILTER_ORDER.find(item => LICENSE_TIER_FEATURES[item].includes(feature));
        return tier ? LICENSE_TIER_LABELS[tier] : '';
    }
}
