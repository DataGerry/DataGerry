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

import { ComponentFixture, TestBed } from '@angular/core/testing';

import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { WORKSPACE_RESET_CONFIRMATION } from '../../models/onboarding-assistant.model';
import { OnboardingResetConfirmationModalComponent } from './onboarding-reset-confirmation-modal.component';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('OnboardingResetConfirmationModalComponent', () => {
    let fixture: ComponentFixture<OnboardingResetConfirmationModalComponent>;
    let component: OnboardingResetConfirmationModalComponent;
    let activeModal: jasmine.SpyObj<NgbActiveModal>;

    beforeEach(async () => {
        activeModal = jasmine.createSpyObj('NgbActiveModal', ['close', 'dismiss']);

        await TestBed.configureTestingModule({
            imports: [OnboardingResetConfirmationModalComponent],
            providers: [{ provide: NgbActiveModal, useValue: activeModal }]
        }).compileComponents();

        fixture = TestBed.createComponent(OnboardingResetConfirmationModalComponent);
        component = fixture.componentInstance;
        fixture.detectChanges();
    });

    it('does not confirm with only the phrase typed', () => {
        component.confirmationControl.setValue(WORKSPACE_RESET_CONFIRMATION);

        component.onConfirm();

        expect(component.completedChecks()).toBe(1);
        expect(activeModal.close).not.toHaveBeenCalled();
    });

    it('does not confirm with only the sum solved', () => {
        component.onMathSolvedChange(true);

        component.onConfirm();

        expect(activeModal.close).not.toHaveBeenCalled();
    });

    it('ignores a phrase in the wrong case', () => {
        component.confirmationControl.setValue(WORKSPACE_RESET_CONFIRMATION.toLowerCase());

        expect(component.isTextConfirmed()).toBeFalse();
    });

    it('confirms once both checks pass', () => {
        component.confirmationControl.setValue(` ${WORKSPACE_RESET_CONFIRMATION} `);
        component.onMathSolvedChange(true);
        fixture.detectChanges();

        component.onConfirm();

        expect(activeModal.close).toHaveBeenCalledOnceWith('confirmed');
        expect(fixture.nativeElement.querySelector('.reset-checks__progress').textContent).toContain('2 of 2 done');
    });
});
