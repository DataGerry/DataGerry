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
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';

import { BuilderKernelModule } from '../builder-kernel.module';
import { ValidationService } from '../services/validation.service';
import { SingleSectionBuilderHost } from './single-section-builder.host';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * The section-template side of the shared section card. Both of these fail silently rather than
 * throwing when they break, so they are worth pinning down:
 * the fixed section binds its editor statically and drives the model from the editor's output.
 */
@Component({
    standalone: true,
    imports: [BuilderKernelModule],
    template: `<section><dg-builder-section [section]="section" [host]="host"><hr></dg-builder-section></section>`
})
class FixedSectionHostComponent {
    public section: any = { name: 'section_template-1', label: 'Template', type: 'section', fields: [] };
    public host = new SingleSectionBuilderHost(() => this.section, this.validationService);

    constructor(public validationService: ValidationService) {}
}


describe('BuilderSectionComponent (fixed single section)', () => {
    let fixture: ComponentFixture<FixedSectionHostComponent>;
    let element: HTMLElement;

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            imports: [FixedSectionHostComponent],
            providers: [
                provideHttpClient(withInterceptorsFromDi()),
                provideHttpClientTesting()
            ]
        }).compileComponents();

        fixture = TestBed.createComponent(FixedSectionHostComponent);
        fixture.detectChanges();
        element = fixture.nativeElement;
    });


    it('binds the section editor statically and hides the header actions', () => {
        expect(element.querySelector('cmdb-section-field-edit')).toBeTruthy();
        expect(element.querySelector('dg-builder-section > .card > .card-header .float-end')).toBeNull();
        expect(element.querySelector('dg-builder-section hr')).toBeTruthy();
    });


    it('applies an editor change to the section through the host', () => {
        const editorElement = element.querySelector('cmdb-section-field-edit');
        const editor: any = fixture.debugElement.query(node => node.nativeElement === editorElement).componentInstance;

        editor.labelControl.setValue('Typed Label');
        fixture.detectChanges();

        expect(fixture.componentInstance.section.label).toBe('Typed Label');
        expect(element.textContent).toContain('Typed Label');
    });


    /**
     * ngx-drag-drop puts the payload through `JSON.stringify` on dragstart and `JSON.parse` on drop,
     * so `event.data` is ALWAYS a fresh object — never the array entry that was dragged. Handing a
     * drop handler the live reference is the single easiest way to write a reorder test that passes
     * while the feature duplicates the field in the browser.
     */
    function dropEvent(payload: any, index: number, dropEffect: string): any {
        return { data: JSON.parse(JSON.stringify(payload)), index, dropEffect };
    }

    it('adds dropped fields and reorders them without duplicating', () => {
        const host = fixture.componentInstance.host;
        const section = fixture.componentInstance.section;

        host.onFieldDrop(dropEvent({ name: 'n1', label: 'Number', type: 'number' }, 0, 'copy'), section);
        host.onFieldDrop(dropEvent({ name: 't1', label: 'Text', type: 'text' }, 1, 'copy'), section);
        fixture.detectChanges();

        expect(section.fields.map((field: any) => field.name)).toEqual(['n1', 't1']);
        expect(element.querySelectorAll('.fields.card').length).toBe(2);

        host.onFieldDrop(dropEvent(section.fields[1], 0, 'move'), section);

        expect(section.fields.map((field: any) => field.name)).toEqual(['t1', 'n1']);
        expect(section.fields.length).withContext('the field must not be duplicated').toBe(2);
    });


    it('keeps the dragged field\'s own object, not the deserialized copy', () => {
        const host = fixture.componentInstance.host;
        const section = fixture.componentInstance.section;

        host.onFieldDrop(dropEvent({ name: 'n1', label: 'Number', type: 'number' }, 0, 'copy'), section);
        host.onFieldDrop(dropEvent({ name: 't1', label: 'Text', type: 'text' }, 1, 'copy'), section);

        const original = section.fields[1];
        host.onFieldDrop(dropEvent(original, 0, 'move'), section);

        expect(section.fields[0]).toBe(original);
    });


    /**
     * The old section-template page bound no `[fieldSectionType]` on its field editors, so the
     * multi-data-section "hide this field as column" checkbox never appeared there. The shared
     * section card passes it for every host, which would surface a control this page cannot honour:
     * its `hideField` change is not routed to `hidden_fields`, it would just be written onto the
     * field and serialised straight into the saved template.
     */
    it('does not offer the multi-data-section hide control on a section template', () => {
        const host = fixture.componentInstance.host;
        const section = fixture.componentInstance.section;
        section.type = 'multi-data-section';

        host.onFieldDrop(dropEvent({ name: 't1', label: 'Text', type: 'text' }, 0, 'copy'), section);
        fixture.detectChanges();

        expect(element.querySelector('.fields.card')).withContext('the field card renders').toBeTruthy();
        expect(element.querySelector('input[name^="hideFieldControl"]')).toBeNull();
    });


    it('never writes a hideField flag onto a section template field', () => {
        const host = fixture.componentInstance.host;
        const section = fixture.componentInstance.section;
        section.type = 'multi-data-section';

        host.onFieldDrop(dropEvent({ name: 't1', label: 'Text', type: 'text' }, 0, 'copy'), section);
        host.onValuesChanged({ newValue: true, inputName: 'hideField', fieldName: 't1', elementType: 'text' });

        expect(section.fields[0].hideField)
            .withContext('a stray hideField would be serialised into the saved template')
            .toBeUndefined();
    });


    it('removes a field and releases its validation entry', () => {
        const host = fixture.componentInstance.host;
        const section = fixture.componentInstance.section;
        const validationService = fixture.componentInstance.validationService;
        spyOn(validationService, 'updateFieldValidityOnDeletion');

        host.onFieldDrop({ data: { name: 'n1', label: 'Number', type: 'number' }, dropEffect: 'copy', index: 0 } as any, section);
        host.onFieldRemove(section.fields[0], section);

        expect(section.fields.length).toBe(0);
        expect(validationService.updateFieldValidityOnDeletion).toHaveBeenCalledWith('n1');
    });
});
