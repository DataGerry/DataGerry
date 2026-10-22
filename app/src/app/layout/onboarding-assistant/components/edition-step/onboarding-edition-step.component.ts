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

import { ChangeDetectionStrategy, Component, model } from '@angular/core';

import { EDITION_OPTIONS, OnboardingEdition } from '../../models/onboarding-assistant.model';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-onboarding-edition-step',
    templateUrl: './onboarding-edition-step.component.html',
    styleUrls: ['./onboarding-edition-step.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class OnboardingEditionStepComponent {
    public readonly selectedEdition = model.required<OnboardingEdition>();

    public readonly editionOptions = EDITION_OPTIONS;
}
