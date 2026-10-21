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
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { ReactiveFormsModule } from '@angular/forms';
import { Location } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { of } from 'rxjs';

import { RiskAssessmentAddComponent } from './risk-assessment-add.component';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { RiskAssessmentService } from '../../services/risk-assessment.service';
import { IsmsValidationService } from '../../services/isms-validation.service';
import { RiskService } from '../../services/risk.service';
import { ImpactCategoryService } from '../../services/impact-category.service';
import { ImpactService } from '../../services/impact.service';
import { LikelihoodService } from '../../services/likelihood.service';
import { ExtendableOptionService } from '../../services/extendable-option.service';
import { ObjectService } from 'src/app/framework/services/object.service';
import { ObjectGroupService } from 'src/app/framework/services/object-group.service';
import { PersonService } from '../../services/person.service';
import { PersonGroupService } from '../../services/person-group.service';
import { RiskMatrixService } from '../../services/risk-matrix.service';
import { RiskClassService } from '../../services/risk-class.service';
import { ControlMeasureService } from '../../services/control-measure.service';
import { ControlMeasureAssignmentService } from '../../services/control‑measure‑assignment.service';

/* -------------------------------------------------------------------------- */
/*                                   HELPERS                                   */
/* -------------------------------------------------------------------------- */

const REQUIRED_MISSING_MESSAGE = 'Please fill in all required fields before saving.';

describe('RiskAssessmentAddComponent', () => {
    let component: RiskAssessmentAddComponent;
    let fixture: ComponentFixture<RiskAssessmentAddComponent>;

    let toast: { success: jasmine.Spy; error: jasmine.Spy };
    let loader: { show: jasmine.Spy; hide: jasmine.Spy };
    let raService: { createRiskAssessment: jasmine.Spy; updateRiskAssessment: jasmine.Spy };
    let location: { back: jasmine.Spy };

    /** The route mode (add / edit / view) is derived at construction, so it must be set per test. */
    const setup = async (opts: { url?: string; params?: Record<string, string> } = {}): Promise<void> => {
        const url = opts.url ?? '/isms/risk-assessments/add';
        const params = opts.params ?? {};

        toast = { success: jasmine.createSpy('success'), error: jasmine.createSpy('error') };
        loader = { show: jasmine.createSpy('show'), hide: jasmine.createSpy('hide') };
        raService = {
            createRiskAssessment: jasmine.createSpy('create').and.returnValue(of({ public_id: 1 })),
            updateRiskAssessment: jasmine.createSpy('update').and.returnValue(of({ public_id: 1 }))
        };
        location = { back: jasmine.createSpy('back') };

        const routerMock = {
            url,
            getCurrentNavigation: () => null,
            navigate: jasmine.createSpy('navigate')
        };
        const routeMock = {
            snapshot: {
                paramMap: {
                    has: (key: string) => key in params,
                    get: (key: string) => (key in params ? params[key] : null)
                }
            }
        };

        await TestBed.configureTestingModule({
            declarations: [RiskAssessmentAddComponent],
            imports: [ReactiveFormsModule],
            providers: [
                { provide: Router, useValue: routerMock },
                { provide: ActivatedRoute, useValue: routeMock },
                { provide: Location, useValue: location },
                { provide: ToastService, useValue: toast },
                { provide: LoaderService, useValue: loader },
                { provide: RiskAssessmentService, useValue: raService },
                { provide: IsmsValidationService, useValue: { checkConfigSilently: () => of(true) } },
                // Reference-data services are only touched by ngOnInit, which these tests do not trigger.
                { provide: RiskService, useValue: {} },
                { provide: ImpactCategoryService, useValue: {} },
                { provide: ImpactService, useValue: {} },
                { provide: LikelihoodService, useValue: {} },
                { provide: ExtendableOptionService, useValue: {} },
                { provide: ObjectService, useValue: {} },
                { provide: ObjectGroupService, useValue: {} },
                { provide: PersonService, useValue: {} },
                { provide: PersonGroupService, useValue: {} },
                { provide: RiskMatrixService, useValue: {} },
                { provide: RiskClassService, useValue: {} },
                { provide: ControlMeasureService, useValue: {} },
                { provide: ControlMeasureAssignmentService, useValue: {} }
            ],
            schemas: [NO_ERRORS_SCHEMA]
        })
            .overrideComponent(RiskAssessmentAddComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(RiskAssessmentAddComponent);
        component = fixture.componentInstance;
    };

    /** Populate every required control so the form becomes valid. */
    const fillRequiredFields = (): void => {
        component.form.patchValue({
            risk_id: 1,
            object_id_ref_type: 'OBJECT',
            object_id: 10,
            risk_owner_id: 5,
            risk_assessment_date: '2026-07-25'
        });
    };

    it('creates the component', async () => {
        await setup();
        expect(component).toBeTruthy();
    });

    /* ----------------------------- REQUIRED WIRING ---------------------------- */

    describe('required-field wiring', () => {
        it('requires the visible risk_owner_id control, not the hidden ref type', async () => {
            await setup();

            const owner = component.form.get('risk_owner_id')!;
            const refType = component.form.get('risk_owner_id_ref_type')!;

            owner.setValue(null);
            refType.setValue(null);
            expect(owner.valid).toBeFalse();   // required drives invalidity
            expect(refType.valid).toBeTrue();  // ref type is no longer required

            owner.setValue(5);
            expect(owner.valid).toBeTrue();
        });
    });

    /* -------------------------- BLOCKED SUBMISSIONS --------------------------- */

    describe('onSave blocks the backend call when required fields are missing', () => {
        it('does not call the API and surfaces a friendly error toast', async () => {
            await setup();

            component.onSave();

            expect(raService.createRiskAssessment).not.toHaveBeenCalled();
            expect(raService.updateRiskAssessment).not.toHaveBeenCalled();
            expect(toast.error).toHaveBeenCalledWith(REQUIRED_MISSING_MESSAGE);
            expect(component.submitAttempted).toBeTrue();
        });

        it('expands the collapsed section that holds a missing required field', async () => {
            await setup();
            expect(component.expandedSections.before).toBeFalse();

            component.onSave();

            expect(component.expandedSections.before).toBeTrue();
            expect(component.invalidSections.before).toBeTrue();
        });

        it('does not flag sections whose required fields are complete', async () => {
            await setup();

            component.onSave();

            expect(component.invalidSections.treatment).toBeFalse();
            expect(component.invalidSections.after).toBeFalse();
            expect(component.invalidSections.audit).toBeFalse();
            expect(component.expandedSections.treatment).toBeFalse();
        });

        it('clears a section flag once its required fields are completed', async () => {
            await setup();
            component.onSave();
            expect(component.invalidSections.before).toBeTrue();

            component.form.patchValue({ risk_owner_id: 5, risk_assessment_date: '2026-07-25' });

            expect(component.invalidSections.before).toBeFalse();
        });
    });

    /* --------------------------- VALID SUBMISSIONS ---------------------------- */

    describe('onSave with a valid form', () => {
        it('creates the risk assessment in add mode', async () => {
            await setup();
            fillRequiredFields();

            component.onSave();

            expect(toast.error).not.toHaveBeenCalled();
            expect(raService.createRiskAssessment).toHaveBeenCalledTimes(1);
            expect(raService.updateRiskAssessment).not.toHaveBeenCalled();
            expect(toast.success).toHaveBeenCalledWith('Risk Assessment created!');
            expect(location.back).toHaveBeenCalled();
        });

        it('updates the risk assessment in edit mode', async () => {
            await setup({ url: '/isms/risk-assessments/edit/123', params: { id: '123' } });
            (component as unknown as { treatmentBlock: unknown }).treatmentBlock = {
                buildAssignmentsPayload: () => []
            };
            fillRequiredFields();

            component.onSave();

            expect(raService.createRiskAssessment).not.toHaveBeenCalled();
            expect(raService.updateRiskAssessment).toHaveBeenCalledTimes(1);
            expect(raService.updateRiskAssessment.calls.mostRecent().args[0]).toBe(123);
            expect(toast.success).toHaveBeenCalledWith('Risk Assessment updated!');
            expect(location.back).toHaveBeenCalled();
        });
    });

    /* ------------------------------- VIEW MODE -------------------------------- */

    describe('onSave in view mode', () => {
        it('never validates or calls the API', async () => {
            await setup({ url: '/isms/risk-assessments/view/5', params: { id: '5' } });

            component.onSave();

            expect(component.submitAttempted).toBeFalse();
            expect(toast.error).not.toHaveBeenCalled();
            expect(raService.createRiskAssessment).not.toHaveBeenCalled();
            expect(raService.updateRiskAssessment).not.toHaveBeenCalled();
        });
    });
});
