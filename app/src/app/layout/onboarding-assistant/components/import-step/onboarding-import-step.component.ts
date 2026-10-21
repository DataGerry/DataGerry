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

import { ChangeDetectionStrategy, Component, input, model } from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';

import { CoreModule } from '../../../../core/core.module';
import { ImportOption, OnboardingImportSource } from '../../models/onboarding-assistant.model';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-onboarding-import-step',
    templateUrl: './onboarding-import-step.component.html',
    styleUrls: ['./onboarding-import-step.component.scss'],
    imports: [ReactiveFormsModule, CoreModule],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class OnboardingImportStepComponent {
    public readonly selectedSource = model<OnboardingImportSource | null>(null);

    /** Owned by the assistant so the file survives moving between steps. */
    public readonly dataModelFile = input.required<FormControl<File | null>>();

    public readonly importOptions: ImportOption[] = [
        {
            id: 'empty',
            icon: 'fas fa-file',
            title: 'Empty data model',
            description: 'Start without a data model and create your own types and categories.'
        },
        {
            id: 'data-model',
            icon: 'fas fa-file-import',
            title: 'Import data model',
            description: 'Upload a data model file exported from another DATAGERRY instance.'
        }
    ];
}
