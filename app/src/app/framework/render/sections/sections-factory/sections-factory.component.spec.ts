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
import { NO_ERRORS_SCHEMA } from '@angular/core';
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
