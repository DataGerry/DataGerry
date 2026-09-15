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
import { KeyValueDiffers, NO_ERRORS_SCHEMA } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { RelationFieldsStepComponent } from './relation-fields-step.component';
import { RelationSchemaAdapter } from 'src/app/framework/builder/schema/relation-schema.adapter';
import { CmdbMode } from 'src/app/framework/modes.enum';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('RelationFieldsStepComponent (relation content step)', () => {

    let fixture: ComponentFixture<RelationFieldsStepComponent>;
    let component: RelationFieldsStepComponent;

    function relation(overrides: any = {}): any {
        return {
            sections: [{ type: 'section', name: 's1', label: 'S1', fields: ['f1'] }],
            fields: [{ name: 'f1', type: 'text' }],
            ...overrides
        };
    }

    /**
     * Applies the input the way the wizard's template does. `setInput` resolves through the same
     * input map a template binding uses, so it exercises the aliased setter rather than writing the
     * base class' plain property behind its back.
     */
    function bind(instance: any, mode: CmdbMode = CmdbMode.Edit): void {
        fixture.componentRef.setInput('relationInstance', instance);
        fixture.componentRef.setInput('mode', mode);
        fixture.detectChanges();
    }

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            declarations: [RelationFieldsStepComponent],
            providers: [KeyValueDiffers],
            schemas: [NO_ERRORS_SCHEMA]
        }).compileComponents();

        fixture = TestBed.createComponent(RelationFieldsStepComponent);
        component = fixture.componentInstance;
    });

    /* --------------------------------------------- SCHEMA BINDING --------------------------------------------- */

    /**
     * The step aliases `relationInstance` onto a setter while its base class declares the same input
     * as a plain property. If the base ever wins, the setter never runs, `schema` stays null and the
     * canvas silently renders an empty builder - with nothing in the compiler or the AOT check to
     * notice.
     */
    it('builds the schema when the input is applied', () => {
        bind(relation());

        expect(component.relationInstance).toBeTruthy();
        expect(component.schema).withContext('the aliased setter must run').toBeTruthy();
        expect(component.schema instanceof RelationSchemaAdapter).toBeTrue();
    });


    it('reads sections and fields off the relation root, not off render_meta', () => {
        const instance = relation();
        bind(instance);

        expect(component.schema.readSections()).toBe(instance.sections);
        expect(component.schema.readFields()).toBe(instance.fields);
        expect(component.schema.readGlobalTemplateIds()).toEqual([]);
        expect(component.schema.readExternals()).toEqual([]);
    });


    it('drops the schema again when the instance is cleared', () => {
        bind(relation());
        fixture.componentRef.setInput('relationInstance', null);

        expect(component.schema).toBeNull();
    });

    /* ------------------------------------------------ PALETTE ------------------------------------------------- */

    it('offers a plain section plus the basic controls, and nothing else', () => {
        bind(relation());

        const groups = component.paletteGroups;

        expect(groups.map(group => group.id)).toEqual(['structureControls', 'basicControls']);
        expect(groups[0].items.map(item => item.label)).toEqual(['Section']);
        expect(groups[1].items.map(item => item.label.toLowerCase())).toEqual([
            'text', 'number', 'password', 'textarea', 'checkbox', 'radio', 'select', 'date'
        ]);

        // No multi-data-section, no ref-section, no special controls, no section templates.
        const labels = groups.flatMap(group => group.items.map(item => item.label.toLowerCase()));
        expect(labels).not.toContain('reference');
        expect(labels).not.toContain('location');
        expect(groups.flatMap(group => group.items.map(item => item.dndType))).not.toContain('location');
    });

    /* ------------------------------------------------ VALIDITY ------------------------------------------------ */

    /** A relation with no sections stays savable. This differs from a type on purpose. */
    it('treats zero sections as a valid content step', () => {
        bind(relation({ sections: [], fields: [] }));

        expect(component.status).toBeTrue();
    });


    it('is invalid while any section has no fields', () => {
        bind(relation({
            sections: [{ type: 'section', name: 's1', label: 'S1', fields: [] }],
            fields: []
        }));

        expect(component.status).toBeFalse();
    });

    /* ------------------------------------------------ ADVISORY ------------------------------------------------ */

    it('flags the structural-change advisory only for a relation that already has fields', () => {
        bind(relation());
        expect(component.initialFieldsPresent).toBeTrue();

        const empty = TestBed.createComponent(RelationFieldsStepComponent);
        empty.componentRef.setInput('relationInstance', relation({ sections: [], fields: [] }));
        empty.detectChanges();

        expect(empty.componentInstance.initialFieldsPresent).toBeFalse();
    });
});
