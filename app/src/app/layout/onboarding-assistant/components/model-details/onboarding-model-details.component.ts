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

import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';

import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { CoreModule } from '../../../../core/core.module';
import {
    BestPracticeModelDetails,
    BestPracticeTypeRef,
    MODEL_DETAILS_TITLE_ID
} from '../../models/onboarding-best-practice.model';
import { toCountItems, toFeatureList, toTypeGroups, toTypeLabelList } from '../../utils/onboarding-best-practice.util';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Closes with `'select'` when the user picks the model. */
@Component({
    selector: 'cmdb-onboarding-model-details',
    templateUrl: './onboarding-model-details.component.html',
    styleUrls: ['./onboarding-model-details.component.scss'],
    imports: [CoreModule],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class OnboardingModelDetailsComponent {
    public readonly activeModal = inject(NgbActiveModal);

    public readonly titleId = MODEL_DETAILS_TITLE_ID;

    /** Set by the opener. */
    public readonly details = signal<BestPracticeModelDetails | null>(null);
    public readonly isSelected = signal(false);

    public readonly countItems = computed(() => {
        const details = this.details();
        return details ? toCountItems(details.counts) : [];
    });

    public readonly lockedMessage = computed(() => {
        const details = this.details();

        return details && !details.applicable
            ? `This model needs ${toFeatureList(details.missing_features)}, which your license does not include.`
            : '';
    });

    public readonly typeGroups = computed(() => {
        const details = this.details();
        return details ? toTypeGroups(details) : [];
    });

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public typeLabels(types: BestPracticeTypeRef[]): string {
        return toTypeLabelList(types);
    }
}
