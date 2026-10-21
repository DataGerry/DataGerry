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

import { FormTextareaComponent } from './form-textarea.component';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('FormTextareaComponent (app-form-textarea)', () => {
    let fixture: ComponentFixture<FormTextareaComponent>;
    let component: FormTextareaComponent;

    const query = <T extends HTMLElement>(selector: string): T =>
        fixture.nativeElement.querySelector(selector);

    beforeEach(async () => {
        await TestBed.configureTestingModule({ declarations: [FormTextareaComponent] }).compileComponents();

        fixture = TestBed.createComponent(FormTextareaComponent);
        component = fixture.componentInstance;
        component.label = 'Port name';
        fixture.detectChanges();
    });

    it('points its label at its own textarea', () => {
        const label = query<HTMLLabelElement>('label');
        const input = query<HTMLTextAreaElement>('textarea');

        expect(input.id).toBe(component.controlId);
        expect(label.getAttribute('for')).toBe(input.id);
    });

    it('gives every instance an id of its own', () => {
        const second = TestBed.createComponent(FormTextareaComponent).componentInstance;

        expect(second.controlId).not.toBe(component.controlId);
    });

    it('announces an error message through the textarea', () => {
        component.errorMessage = 'A port needs a name.';
        fixture.detectChanges();

        const input = query<HTMLTextAreaElement>('textarea');

        expect(input.getAttribute('aria-invalid')).toBe('true');
        expect(input.getAttribute('aria-describedby')).toBe(query('.invalid-feedback').id);
    });

    it('carries no error wiring while the value is valid', () => {
        const input = query<HTMLTextAreaElement>('textarea');

        expect(input.getAttribute('aria-invalid')).toBeNull();
        expect(input.getAttribute('aria-describedby')).toBeNull();
    });
});
