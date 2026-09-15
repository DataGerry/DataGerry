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
import { ComponentFixture, TestBed, fakeAsync, tick, flush } from '@angular/core/testing';
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';

import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';
import { DndModule } from 'ngx-drag-drop';
import { Subject } from 'rxjs';

import { SectionTemplateBuilderComponent } from './section-template-builder.component';
import { SectionTemplateService } from '../../services/section-template.service';
import { BuilderKernelModule } from 'src/app/framework/builder/builder-kernel.module';
import { SectionIdentifierService } from 'src/app/framework/builder/services/SectionIdentifierService.service';
import { ValidationService } from 'src/app/framework/builder/services/validation.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
/* ------------------------------------------------------------------------------------------------------------------ */

const IDENTIFIER_ERROR = 'Identifier must be unique';

/**
 * The page with its real section editor, reached the way a user reaches it: through the app, after
 * a type builder has already run. The identifier registry is app-wide, and this page registers
 * nothing with it - so anything it left behind must not be able to flag this page's identifier.
 */
describe('SectionTemplateBuilderComponent identifier state', () => {

    let component: SectionTemplateBuilderComponent;
    let fixture: ComponentFixture<SectionTemplateBuilderComponent>;
    let sectionTemplateService: jasmine.SpyObj<SectionTemplateService>;
    let registry: SectionIdentifierService;

    beforeEach(async () => {
        sectionTemplateService = jasmine.createSpyObj<SectionTemplateService>(
            'SectionTemplateService', ['getSectionTemplate', 'postSectionTemplate', 'updateSectionTemplate']
        );

        await TestBed.configureTestingModule({
            declarations: [SectionTemplateBuilderComponent],
            imports: [ReactiveFormsModule, FormsModule, FontAwesomeModule, DndModule, BuilderKernelModule],
            providers: [
                { provide: SectionTemplateService, useValue: sectionTemplateService },
                { provide: ToastService, useValue: jasmine.createSpyObj('ToastService', ['error', 'success']) },
                { provide: Router, useValue: jasmine.createSpyObj('Router', ['navigate']) },
                provideHttpClient(),
                provideHttpClientTesting(),
                SectionIdentifierService,
                ValidationService
            ],
            schemas: [NO_ERRORS_SCHEMA]
        }).compileComponents();

        fixture = TestBed.createComponent(SectionTemplateBuilderComponent);
        component = fixture.componentInstance;
        registry = TestBed.inject(SectionIdentifierService);
    });


    /** A type builder registered its sections, the user focused one, then navigated away. */
    function leaveTypeBuilderBehind(): void {
        registry.syncSections(['type_section_a', 'type_section_b']);
        registry.setActiveIndex(1);
        registry.resetIdentifiers();
    }


    function renderedText(): string {
        tick(400);
        flush();
        fixture.detectChanges();

        return fixture.nativeElement.textContent;
    }


    it('does not flag the identifier of a multi-data-section template being edited', fakeAsync(() => {
        // Only a multi-data-section runs the identifier sync on every change, which is why plain
        // templates looked fine while this one reported a conflict until the page was reloaded.
        leaveTypeBuilderBehind();

        const response = new Subject<any>();
        sectionTemplateService.getSectionTemplate.and.returnValue(response.asObservable());
        component.sectionTemplateID = 23;
        fixture.detectChanges();

        response.next({
            public_id: 23,
            name: 'section_template-2fe3b0ef',
            label: 'clone ports',
            type: 'multi-data-section',
            is_global: false,
            predefined: false,
            fields: [{ type: 'text', name: 'text-8bba97d2', label: 'Name', required: true }]
        });

        expect(renderedText()).not.toContain(IDENTIFIER_ERROR);
    }));


    it('does not flag the identifier of a new global multi-data-section template', fakeAsync(() => {
        leaveTypeBuilderBehind();

        component.sectionTemplateID = 0;
        fixture.detectChanges();

        component.formGroup.controls['isMultiDataSection'].setValue(true);
        component.formGroup.controls['isGlobal'].setValue(true);
        fixture.detectChanges();

        expect(component.initialSection.name.startsWith('dg_gst-')).toBeTrue();
        expect(renderedText()).not.toContain(IDENTIFIER_ERROR);
    }));
});
