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
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';

import { of } from 'rxjs';

import { RelationBuilderComponent } from './relation-builder.component';
import { RelationService } from '../../services/relaion.service';
import { ToastService } from '../../../layout/toast/toast.service';
import { ValidationService } from 'src/app/framework/builder/services/validation.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { CmdbMode } from '../../modes.enum';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('RelationBuilderComponent (relation wizard)', () => {

    let component: RelationBuilderComponent;
    let relationService: jasmine.SpyObj<RelationService>;
    let toast: jasmine.SpyObj<ToastService>;

    beforeEach(() => {
        relationService = jasmine.createSpyObj<RelationService>('RelationService', ['postRelation', 'putRelation']);
        relationService.postRelation.and.returnValue(of({ public_id: 1 } as any));
        relationService.putRelation.and.returnValue(of({ public_id: 1 } as any));
        toast = jasmine.createSpyObj<ToastService>('ToastService', ['error', 'success']);

        TestBed.configureTestingModule({
            providers: [
                RelationBuilderComponent,
                ValidationService,
                { provide: RelationService, useValue: relationService },
                { provide: ToastService, useValue: toast },
                { provide: Router, useValue: jasmine.createSpyObj('Router', ['navigate']) },
                { provide: LoaderService, useValue: { show: () => { }, hide: () => { }, isLoading$: of(false) } },
                { provide: ActivatedRoute, useValue: { snapshot: { routeConfig: { path: 'edit/:publicID' } } } }
            ]
        });

        component = TestBed.inject(RelationBuilderComponent);
        component.mode = CmdbMode.Edit;
        component.basicValid = true;
        component.contentValid = true;
        component.blocking.isSectionWithoutFields = true;
    });

    /* ------------------------------------------------ SAVE PAYLOAD ------------------------------------------------ */

    /**
     * A section's `fields` hold plain names at rest and resolved field objects once the canvas has
     * written its hydrated projection back. Which of the two a section carries depends on whether
     * the user touched it, so a save has to survive both - otherwise opening an existing relation
     * and saving it untouched would send `undefined` for every field name.
     */
    it('flattens field names whether the section carries names or field objects', () => {
        component.relationInstance = {
            relation_name: 'r', parent_type_ids: [1], child_type_ids: [2], description: '',
            sections: [
                { type: 'section', name: 'untouched', label: 'U', fields: ['a', 'b'] },
                { type: 'section', name: 'mutated', label: 'M', fields: [{ name: 'c', type: 'text' }] }
            ],
            fields: [{ name: 'a' }, { name: 'b' }, { name: 'c' }]
        } as any;

        component.saveRelation();

        const sent: any = relationService.putRelation.calls.mostRecent().args[0];
        expect(sent.sections[0].fields).toEqual(['a', 'b']);
        expect(sent.sections[1].fields).toEqual(['c']);
        expect(sent.fields.length).toBe(3);
    });


    it('saves a relation with no sections', () => {
        component.relationInstance = {
            relation_name: 'r', parent_type_ids: [1], child_type_ids: [2],
            sections: [], fields: []
        } as any;

        component.saveRelation();

        expect(relationService.putRelation).toHaveBeenCalled();
        expect(relationService.putRelation.calls.mostRecent().args[0].sections).toEqual([]);
    });

    /* -------------------------------------------------- SAVE GATE -------------------------------------------------- */

    it('refuses to save while the canvas is blocked, and warns the user', () => {
        component.relationInstance = { sections: [], fields: [] } as any;
        component.blocking.disableFields = true;

        component.saveRelation();

        expect(relationService.putRelation).not.toHaveBeenCalled();
        expect(toast.error).toHaveBeenCalled();
    });


    it('mirrors every ValidationService flag the wizard gates Save on', () => {
        component.blocking.isSectionHighlighted = false;
        component.blocking.isFieldHighlighted = false;
        component.blocking.disableFields = false;
        component.blocking.isSectionWithoutFields = true;
        expect(component.blocking.blocked).toBeFalse();

        component.blocking.isFieldHighlighted = true;
        expect(component.blocking.blocked).toBeTrue();

        component.blocking.isFieldHighlighted = false;
        component.blocking.isSectionWithoutFields = false;
        expect(component.blocking.blocked).toBeTrue();
    });
});
