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
import { UntypedFormControl, UntypedFormGroup } from '@angular/forms';
import { of } from 'rxjs';

import { PersonComponent } from './person.component';
import { PersonRelationsService } from '../../../services/person-relations.service';
import { CmdbMode } from '../../../modes.enum';
import { PersonCandidate, PersonRefKind } from '../../../models/person.model';

const ALICE: PersonCandidate = { ref_type: 'PERSON', id: 11, label: 'Alice', type_id: 3 };
const OPS: PersonCandidate = { ref_type: 'PERSON_GROUP', id: 21, label: 'Ops', type_id: 4 };

describe('PersonComponent', () => {
    let service: jasmine.SpyObj<PersonRelationsService>;

    function create(field: Record<string, unknown>, value: unknown, mode: CmdbMode = CmdbMode.Edit): PersonComponent {
        const component = TestBed.runInInjectionContext(() => new PersonComponent());
        component.parentFormGroup = new UntypedFormGroup({ owner: new UntypedFormControl(value) });
        component.data = { name: 'owner', label: 'Owner', type: 'person', ...field };
        component.mode = mode;
        component.ngOnInit();
        return component;
    }

    beforeEach(() => {
        service = jasmine.createSpyObj<PersonRelationsService>('PersonRelationsService', ['getCandidates', 'resolveSelections']);
        service.getCandidates.and.returnValue(of([ALICE, OPS]));

        TestBed.configureTestingModule({
            providers: [{ provide: PersonRelationsService, useValue: service }]
        });
    });

    it('loads a fresh candidate list of the field kind', () => {
        create({ person_ref_kind: PersonRefKind.PERSON }, null);

        expect(service.getCandidates).toHaveBeenCalledWith(PersonRefKind.PERSON, true);
    });

    it('writes one pair into a single field', () => {
        const component = create({}, null);

        component.onSelectionChange('PERSON_GROUP:21');

        expect(component.controller.value).toEqual({ ref_type: 'PERSON_GROUP', id: 21 });
        expect(component.selectedKeys).toBeNull();
    });

    it('writes null when a single field is cleared', () => {
        const component = create({}, { ref_type: 'PERSON', id: 11 });

        expect(component.selectedKeys).toBe('PERSON:11');
        component.onSelectionChange(null);

        expect(component.controller.value).toBeNull();
    });

    it('writes a list into a multiple field', () => {
        const component = create({ multiple: true }, []);

        component.onSelectionChange(['PERSON:11', 'PERSON_GROUP:21']);

        expect(component.controller.value).toEqual([
            { ref_type: 'PERSON', id: 11 },
            { ref_type: 'PERSON_GROUP', id: 21 }
        ]);

        component.onSelectionChange([]);
        expect(component.controller.value).toEqual([]);
    });

    it('keeps a stored selection the list no longer offers', () => {
        const component = create({ multiple: true }, [{ ref_type: 'PERSON', id: 99 }]);

        const missing = component.items.find(item => item.id === 99);
        expect(missing?.missing).toBeTrue();
    });

    it('resolves the labels in view mode', () => {
        service.resolveSelections.and.returnValue(of(new Map([['PERSON:11', ALICE]])));

        const component = create({ multiple: true }, [{ ref_type: 'PERSON', id: 11 }], CmdbMode.View);

        expect(service.getCandidates).not.toHaveBeenCalled();
        expect(component.viewSelections.map(entry => entry.label)).toEqual(['Alice']);
    });
});
