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

import { DeploymentInformation } from '../../../../settings/system/models/deployment-information.model';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-onboarding-welcome-step',
    templateUrl: './onboarding-welcome-step.component.html',
    styleUrls: ['./onboarding-welcome-step.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class OnboardingWelcomeStepComponent {
    public readonly isCloud = input.required<boolean>();
    public readonly deployment = input<DeploymentInformation | null>(null);

    /** Falls back to the build mode until the server has answered. */
    public readonly isCloudDeployment = computed(() => {
        const deployment = this.deployment()?.deployment;
        return deployment ? deployment === 'cloud' : this.isCloud();
    });

    public readonly databaseStatus = computed(() => {
        const deployment = this.deployment();

        if (!deployment) {
            return '';
        }

        return deployment.database_reachable ? 'Reachable' : 'Not reachable';
    });
}
