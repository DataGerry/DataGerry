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

import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject } from '@angular/core';

import { CoreModule } from '../../../../core/core.module';
import {
    LICENSE_TIER_FEATURES,
    LICENSE_TIER_FILTER_ORDER,
    LICENSE_TIER_LABELS,
    LicenseFeature,
    SERVICE_PORTAL_URL
} from '../../../../settings/license-management/models/license.model';
import { DAY_IN_MS, PLAN_FEATURES } from '../../models/onboarding-license.model';
import { OnboardingLicenseService } from '../../services/onboarding-license.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-onboarding-plan-step',
    templateUrl: './onboarding-plan-step.component.html',
    styleUrls: ['./onboarding-plan-step.component.scss'],
    imports: [DatePipe, CoreModule],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class OnboardingPlanStepComponent implements OnInit {
    public readonly licenseState = inject(OnboardingLicenseService);

    public readonly servicePortalUrl = SERVICE_PORTAL_URL;

    public readonly features = computed(() => {
        const enabled = this.licenseState.license()?.entitlement.features ?? [];
        const isTrial = this.licenseState.isTrial();

        return PLAN_FEATURES.map(item => ({
            ...item,
            isIncluded: isTrial || enabled.includes(item.feature),
            requiredPlan: this.requiredPlanOf(item.feature)
        }));
    });

    public readonly heading = computed(() => {
        if (this.licenseState.isTrial()) {
            return 'Your trial';
        }

        return this.licenseState.license() ? 'Your subscription' : 'Your plan';
    });

    public readonly lead = computed(() => {
        const license = this.licenseState.license();

        if (this.licenseState.isTrial()) {
            const length = this.trialLengthInDays();
            const trial = length ? `the ${length}-day trial` : 'the trial';

            return `During ${trial} you get the full feature set. Afterwards you choose a plan in the Service Portal.`;
        }

        if (license?.is_active) {
            return 'Your plan is active. These features are available to you.';
        }

        return 'Your DATAGERRY Cloud plan decides which Pro features your workspace includes.';
    });

    public readonly cardTitle = computed(() => {
        const size = this.licenseState.planSize();

        if (!size) {
            return 'Cloud plan';
        }

        return this.licenseState.isTrial() ? `Trial · ${size} scope` : `Subscription ${size}`;
    });

    /** Null when the trial has no start or end date. */
    private readonly trialLengthInDays = computed(() => {
        const entitlement = this.licenseState.license()?.entitlement;

        if (!entitlement?.startDate || !entitlement.endDate) {
            return null;
        }

        return Math.round((entitlement.endDate - entitlement.startDate) / DAY_IN_MS);
    });

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.licenseState.loadCurrentPlan();
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private requiredPlanOf(feature: LicenseFeature): string {
        const tier = LICENSE_TIER_FILTER_ORDER.find(item => LICENSE_TIER_FEATURES[item].includes(feature));
        return tier ? LICENSE_TIER_LABELS[tier] : '';
    }
}
