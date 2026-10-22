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

import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { TourIllustration } from '../../models/onboarding-tour.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Decorative drawing inside a tour card; the step text carries the meaning. */
@Component({
    selector: 'cmdb-onboarding-tour-illustration',
    templateUrl: './onboarding-tour-illustration.component.html',
    styleUrls: ['./onboarding-tour-illustration.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: { 'aria-hidden': 'true' }
})
export class OnboardingTourIllustrationComponent {
    public readonly illustration = input.required<TourIllustration>();
}
