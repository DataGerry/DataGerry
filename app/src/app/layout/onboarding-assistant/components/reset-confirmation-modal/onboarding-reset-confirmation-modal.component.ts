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

* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';

import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { CoreModule } from '../../../../core/core.module';
import { WORKSPACE_RESET_CONFIRMATION } from '../../models/onboarding-assistant.model';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-onboarding-reset-confirmation-modal',
    templateUrl: './onboarding-reset-confirmation-modal.component.html',
    styleUrls: ['./onboarding-reset-confirmation-modal.component.scss'],
    imports: [CoreModule, ReactiveFormsModule],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class OnboardingResetConfirmationModalComponent {
    public readonly activeModal = inject(NgbActiveModal);

    public readonly confirmationText = WORKSPACE_RESET_CONFIRMATION;
    public readonly confirmationControl = new FormControl('', { nonNullable: true });
    public readonly totalChecks = 2;

    private readonly typedText = toSignal(this.confirmationControl.valueChanges, { initialValue: '' });

    public readonly isTextConfirmed = computed(() => this.typedText().trim() === this.confirmationText);
    public readonly isMathSolved = signal(false);
    public readonly completedChecks = computed(() => Number(this.isTextConfirmed()) + Number(this.isMathSolved()));
    public readonly canConfirm = computed(() => this.isTextConfirmed() && this.isMathSolved());

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onMathSolvedChange(isSolved: boolean): void {
        this.isMathSolved.set(isSolved);
    }


    public onConfirm(): void {
        if (!this.canConfirm()) {
            return;
        }

        this.activeModal.close('confirmed');
    }
}
