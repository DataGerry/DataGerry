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
import { Component, NO_ERRORS_SCHEMA } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ReactiveFormsModule, UntypedFormGroup } from '@angular/forms';

import { ToastService } from '../../../../layout/toast/toast.service';
import { RenderResult } from '../../../models/cmdb-render';
import { CmdbMode } from '../../../modes.enum';
import { TextareaComponent } from '../../fields/textarea/textarea.component';
import { RenderElementComponent } from '../../render-element/render-element.component';
import { FieldSectionComponent } from '../field-section/field-section.component';
import { SectionsFactoryComponent } from './sections-factory.component';

/* ------------------------------------------------------------------------------------------------------------------ */

const FIELD_NAME = 'dg-rack-notes';

/** An object as the route hands it over: read from the backend, so every part of it a fresh object. */
const renderResultWith = (notes: string): RenderResult => ({
    sections: [{ type: 'section', name: 'info', label: 'Information', fields: [FIELD_NAME] }],
    fields: [{ name: FIELD_NAME, type: 'textarea', label: 'Notes', value: notes }]
} as RenderResult);

/* ------------------------------------------------------------------------------------------------------------------ */

describe('SectionsFactoryComponent', () => {
    let fixture: ComponentFixture<SectionsFactoryComponent>;
    let form: UntypedFormGroup;

    /** What the rendered field actually shows: in view mode it reads from the control it was built with. */
    const shownValue = () => form.get([FIELD_NAME])?.value;

    const render = (renderResult: RenderResult) => {
        fixture.componentRef.setInput('sections', renderResult.sections);
        fixture.componentRef.setInput('fields', renderResult.fields);
        fixture.componentRef.setInput('values', renderResult.fields);
        fixture.detectChanges();
    };

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            declarations: [
                SectionsFactoryComponent,
                FieldSectionComponent,
                RenderElementComponent,
                TextareaComponent
            ],
            imports: [ReactiveFormsModule],
            providers: [{ provide: ToastService, useValue: {} }],
            schemas: [NO_ERRORS_SCHEMA]
        })
            .overrideComponent(TextareaComponent, { set: { template: '' } })
            .compileComponents();

        form = new UntypedFormGroup({});
        fixture = TestBed.createComponent(SectionsFactoryComponent);
        fixture.componentRef.setInput('mode', CmdbMode.View);
        fixture.componentRef.setInput('form', form);

        render(renderResultWith('first note'));
    });

    it('renders the fields of the object it is given', () => {
        expect(shownValue()).toBe('first note');
    });

    it('rebuilds the fields when the object is replaced, so a re-read shows what was written', () => {
        render(renderResultWith('second note'));

        expect(shownValue()).toBe('second note');
    });

    it('shows a value that was emptied', () => {
        render(renderResultWith(''));

        expect(shownValue()).toBe('');
    });
});


/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * The host template is applied through `overrideComponent`, not the decorator: a spec carries no
 * NgModule, so an inline template referencing `cmdb-sections-factory` has no directive scope in AOT.
 */
const HOST_TEMPLATE = `
    <cmdb-sections-factory
        [mode]="mode"
        [form]="form"
        [sections]="sections"
        [fields]="[]"
        [values]="[]"
        [sectionSlot]="portsSlot"
        [sectionSlotIndex]="portsSlotIndex" />

    <ng-template #portsSlot><span class="ports-marker"></span></ng-template>
`;

/** Marks the slot in the DOM so a test can read where it landed among the sections. */
@Component({ template: '', standalone: false })
class SectionSlotHostComponent {
    public readonly mode = CmdbMode.View;
    public readonly form = new UntypedFormGroup({});
    public sections: Array<any> = [
        { type: 'section', name: 'section_a', label: 'A', fields: [] },
        { type: 'section', name: 'section_b', label: 'B', fields: [] }
    ];
    public portsSlotIndex: number | null = null;
}


describe('SectionsFactoryComponent section slot', () => {
    let fixture: ComponentFixture<SectionSlotHostComponent>;

    /** The rendered order, reading a section as its name and the slot as 'ports'. */
    const renderedOrder = (): Array<string> =>
        Array.from(fixture.nativeElement.querySelectorAll('cmdb-field-section, .ports-marker'))
            .map((element: Element) => element.classList.contains('ports-marker') ? 'ports' : 'section');

    const renderWithSlotAt = (index: number | null) => {
        fixture.componentInstance.portsSlotIndex = index;
        fixture.detectChanges();
    };

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            declarations: [SectionsFactoryComponent, SectionSlotHostComponent],
            imports: [ReactiveFormsModule],
            schemas: [NO_ERRORS_SCHEMA]
        })
            .overrideComponent(SectionSlotHostComponent, { set: { template: HOST_TEMPLATE } })
            .compileComponents();

        fixture = TestBed.createComponent(SectionSlotHostComponent);
    });

    it('renders the slot first for index 0', () => {
        renderWithSlotAt(0);

        expect(renderedOrder()).toEqual(['ports', 'section', 'section']);
    });

    it('renders the slot between the sections for index 1', () => {
        renderWithSlotAt(1);

        expect(renderedOrder()).toEqual(['section', 'ports', 'section']);
    });

    it('renders the slot last for an index at the end', () => {
        renderWithSlotAt(2);

        expect(renderedOrder()).toEqual(['section', 'section', 'ports']);
    });

    it('clamps an index that outruns the sections instead of dropping the slot', () => {
        renderWithSlotAt(7);

        expect(renderedOrder()).toEqual(['section', 'section', 'ports']);
    });

    it('renders no slot at all without an index', () => {
        renderWithSlotAt(null);

        expect(renderedOrder()).toEqual(['section', 'section']);
    });

    // A ports-only type is saveable, so the slot must survive having no section to sit beside.
    it('renders the slot for a type with no sections of its own', () => {
        fixture.componentInstance.sections = [];
        renderWithSlotAt(0);

        expect(renderedOrder()).toEqual(['ports']);
    });
});
