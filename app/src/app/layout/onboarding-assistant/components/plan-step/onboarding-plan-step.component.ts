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
    LICENSE_FEATURE_LABELS,
    LICENSE_TIER_FEATURES,
    LicenseTier
} from '../../../../settings/license-management/models/license.model';
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

    public readonly features = computed(() => {
        const enabled = this.licenseState.license()?.entitlement.features ?? [];

        return LICENSE_TIER_FEATURES[LicenseTier.Corporate]
            .filter(feature => enabled.includes(feature))
            .map(feature => LICENSE_FEATURE_LABELS[feature]);
    });

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.licenseState.loadCurrentPlan();
    }
}
