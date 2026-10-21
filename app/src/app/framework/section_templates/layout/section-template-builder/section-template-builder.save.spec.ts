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
import { ReactiveFormsModule } from '@angular/forms';
import { RouterTestingModule } from '@angular/router/testing';
import { provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';

import { of } from 'rxjs';

import { SectionTemplateBuilderComponent } from './section-template-builder.component';
import { SectionTemplateService } from '../../services/section-template.service';
import { ValidationService } from 'src/app/framework/builder/services/validation.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { BuilderKernelModule } from 'src/app/framework/builder/builder-kernel.module';
import { CoreModule } from 'src/app/core/core.module';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * The saved name and label are read off `initialSection`, which the section editor writes through
 * the host as the user types. Nothing in the compiler notices if that output stops firing - the page
 * would just save its generated placeholder label instead of the typed one - so the payload is
 * asserted against a real, rendered editor rather than a stub.
 */
describe('SectionTemplateBuilderComponent (save payload)', () => {

    let component: SectionTemplateBuilderComponent;
    let fixture: ComponentFixture<SectionTemplateBuilderComponent>;
    let sectionTemplateService: jasmine.SpyObj<SectionTemplateService>;

    /** The rendered section editor instance, i.e. what the user actually types into. */
    function sectionEditor(): any {
        const element = fixture.nativeElement.querySelector('cmdb-section-field-edit');
        return fixture.debugElement.query(node => node.nativeElement === element).componentInstance;
    }

    function dropField(name: string): void {
        component.sectionHost.onFieldDrop(
            { data: { name, label: name.toUpperCase(), type: 'text' }, dropEffect: 'copy', index: 0 } as any,
            component.initialSection
        );
    }

    beforeEach(async () => {
        sectionTemplateService = jasmine.createSpyObj<SectionTemplateService>(
            'SectionTemplateService', ['getSectionTemplate', 'postSectionTemplate', 'updateSectionTemplate']
        );
        sectionTemplateService.postSectionTemplate.and.returnValue(of({} as any));
        sectionTemplateService.updateSectionTemplate.and.returnValue(of({} as any));

        await TestBed.configureTestingModule({
            declarations: [SectionTemplateBuilderComponent],
            imports: [ReactiveFormsModule, RouterTestingModule, BuilderKernelModule, CoreModule],
            providers: [
                { provide: SectionTemplateService, useValue: sectionTemplateService },
                { provide: ToastService, useValue: jasmine.createSpyObj('ToastService', ['error', 'success']) },
                ValidationService,
                provideHttpClient(withInterceptorsFromDi()),
                provideHttpClientTesting()
            ]
        }).compileComponents();

        fixture = TestBed.createComponent(SectionTemplateBuilderComponent);
        component = fixture.componentInstance;
        component.sectionTemplateID = 0;
        fixture.detectChanges();
    });

    /* -------------------------------------------------- CREATE -------------------------------------------------- */

    it('sends the label typed into the section editor', () => {
        sectionEditor().labelControl.setValue('Contact Block');
        fixture.detectChanges();

        dropField('f1');
        component.isFormValid = true;
        component.handleSectionTemplate();

        const payload: any = sectionTemplateService.postSectionTemplate.calls.mostRecent().args[0];
        expect(payload.label).toBe('Contact Block');
        expect(payload.name).toContain('section_template-');
        expect(payload.is_global).toBeFalse();
        expect(payload.type).toBe('section');
        expect(JSON.parse(payload.fields).map((field: any) => field.name)).toEqual(['f1']);
    });


    it('sends the global identifier once the Global Template toggle is on', () => {
        sectionEditor().labelControl.setValue('Owner');
        component.formGroup.controls['isGlobal'].setValue(true);
        fixture.detectChanges();

        dropField('f1');
        component.isFormValid = true;
        component.handleSectionTemplate();

        const payload: any = sectionTemplateService.postSectionTemplate.calls.mostRecent().args[0];
        expect(payload.name).toContain('dg_gst-');
        expect(payload.name).toBe(component.initialSection.name);
        expect(payload.label).withContext('the Label must survive the rename').toBe('Owner');
        expect(payload.is_global).toBeTrue();
    });


    it('sends multi-data-section as the type when that toggle is on', () => {
        component.formGroup.controls['isMultiDataSection'].setValue(true);
        fixture.detectChanges();

        dropField('f1');
        component.isFormValid = true;
        component.handleSectionTemplate();

        expect(sectionTemplateService.postSectionTemplate.calls.mostRecent().args[0].type)
            .toBe('multi-data-section');
    });

    /* --------------------------------------------------- GATE ---------------------------------------------------- */

    it('refuses to save a section with no fields', () => {
        component.isFormValid = true;

        component.handleSectionTemplate();

        expect(sectionTemplateService.postSectionTemplate).not.toHaveBeenCalled();
        expect(sectionTemplateService.updateSectionTemplate).not.toHaveBeenCalled();
    });


    it('refuses to save while the form is invalid', () => {
        dropField('f1');
        component.isFormValid = false;

        component.handleSectionTemplate();

        expect(sectionTemplateService.postSectionTemplate).not.toHaveBeenCalled();
    });
});
