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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { ReactiveFormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { Subject } from 'rxjs';

import { SectionTemplateBuilderComponent } from './section-template-builder.component';
import { SectionTemplateService } from '../../services/section-template.service';
import { ValidationService } from 'src/app/framework/builder/services/validation.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('SectionTemplateBuilderComponent', () => {

    let component: SectionTemplateBuilderComponent;
    let fixture: ComponentFixture<SectionTemplateBuilderComponent>;
    let sectionTemplateService: jasmine.SpyObj<SectionTemplateService>;

    beforeEach(async () => {
        sectionTemplateService = jasmine.createSpyObj<SectionTemplateService>(
            'SectionTemplateService', ['getSectionTemplate', 'postSectionTemplate', 'updateSectionTemplate']
        );

        await TestBed.configureTestingModule({
            declarations: [SectionTemplateBuilderComponent],
            imports: [ReactiveFormsModule],
            providers: [
                { provide: SectionTemplateService, useValue: sectionTemplateService },
                { provide: ToastService, useValue: jasmine.createSpyObj('ToastService', ['error', 'success']) },
                { provide: Router, useValue: jasmine.createSpyObj('Router', ['navigate']) },
                ValidationService
            ],
            schemas: [NO_ERRORS_SCHEMA]
        }).compileComponents();

        fixture = TestBed.createComponent(SectionTemplateBuilderComponent);
        component = fixture.componentInstance;
    });

    /* -------------------------------------------- PALETTE -------------------------------------------- */

    it('offers the basic controls plus Reference, and nothing else', () => {
        fixture.detectChanges();

        const groups = component.paletteGroups;
        expect(groups.map(group => group.id)).toEqual(['basicControls', 'specialControls']);
        expect(groups[0].expanded).toBeTrue();

        expect(groups[0].items.map(item => item.label.toLowerCase())).toEqual([
            'text', 'number', 'password', 'textarea', 'checkbox', 'radio', 'select', 'date'
        ]);
        expect(groups[1].items.map(item => item.label)).toEqual(['Reference']);

        // No structure control: the section is fixed, so nothing may drop as a section.
        const dndTypes = groups.flatMap(group => group.items.map(item => item.dndType));
        expect(dndTypes).not.toContain('sections');
        expect(dndTypes).not.toContain('location');
    });

    /* ------------------------------------------- HYDRATION ------------------------------------------- */

    describe('loading an existing template', () => {

        /**
         * The response has to arrive AFTER ngOnInit, like a real HTTP call does: ngOnInit registers
         * the isGlobal rename listener only after kicking off the fetch, so a synchronous `of()`
         * would land before the listener exists and hide the very bug this covers.
         */
        function loadTemplateNamed(name: string, isGlobal: boolean, type = 'section') {
            const response = new Subject<any>();
            sectionTemplateService.getSectionTemplate.and.returnValue(response.asObservable());

            component.sectionTemplateID = 5;
            fixture.detectChanges();

            response.next({
                public_id: 5, name, label: 'Contact', type,
                is_global: isGlobal, predefined: false, fields: [{ name: 'a', type: 'text' }]
            });
        }

        it('keeps a stored identifier that carries neither prefix', () => {
            // Hydrating the isGlobal toggle must not emit: the rename listener would otherwise
            // rewrite a perfectly good stored identifier, changing a persisted value on load.
            loadTemplateNamed('legacy_contact_block', false);

            expect(component.initialSection.name).toBe('legacy_contact_block');
        });


        it('keeps a stored global identifier as-is', () => {
            loadTemplateNamed('dg_gst-abc', true);

            expect(component.initialSection.name).toBe('dg_gst-abc');
            expect(component.formGroup.value.isGlobal).toBeTrue();
        });


        it('reflects a multi-data-section template in the toggle without retyping the section', () => {
            loadTemplateNamed('section_template-x', false, 'multi-data-section');

            expect(component.formGroup.value.isMultiDataSection).toBeTrue();
            expect(component.initialSection.type).toBe('multi-data-section');
        });
    });

    /* --------------------------------------- TOGGLING ON CREATE --------------------------------------- */

    describe('toggling on create', () => {

        beforeEach(() => {
            component.sectionTemplateID = 0;
            fixture.detectChanges();
        });

        it('renames into the global namespace and back', () => {
            component.formGroup.controls['isGlobal'].setValue(true);
            expect(component.initialSection.name).toContain('dg_gst-');

            component.formGroup.controls['isGlobal'].setValue(false);
            expect(component.initialSection.name).toContain('section_template-');
        });


        it('reuses the current name when it already carries the right prefix', () => {
            component.formGroup.controls['isGlobal'].setValue(true);
            const globalName = component.initialSection.name;

            // Re-applying the same toggle value must not mint a new identifier.
            component.formGroup.controls['isGlobal'].setValue(true);
            expect(component.initialSection.name).toBe(globalName);
        });


        it('flips the section type with the multi-data-section toggle', () => {
            component.formGroup.controls['isMultiDataSection'].setValue(true);
            expect(component.initialSection.type).toBe('multi-data-section');

            component.formGroup.controls['isMultiDataSection'].setValue(false);
            expect(component.initialSection.type).toBe('section');
        });
    });
});
