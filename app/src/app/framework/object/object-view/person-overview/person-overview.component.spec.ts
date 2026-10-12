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
import { SimpleChange } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { PersonOverviewComponent } from './person-overview.component';
import { PersonRelationsService } from 'src/app/framework/services/person-relations.service';
import { ObjectChangeNotifierService } from 'src/app/framework/services/object-change-notifier.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { SpecialType } from 'src/app/framework/models/special-type';
import { PersonCandidate, PersonRefKind, PersonRelations } from 'src/app/framework/models/person.model';

const ALICE: PersonCandidate = { ref_type: 'PERSON', id: 11, label: 'Alice', type_id: 3 };
const BOB: PersonCandidate = { ref_type: 'PERSON', id: 12, label: 'Bob', type_id: 3 };
const OPS: PersonCandidate = { ref_type: 'PERSON_GROUP', id: 21, label: 'Ops', type_id: 4 };
const DEV: PersonCandidate = { ref_type: 'PERSON_GROUP', id: 22, label: 'Dev', type_id: 4 };

const relations = (overrides: Partial<PersonRelations>): PersonRelations => ({
    ref_type: 'PERSON', memberships: [], members: [], assignments: [], ...overrides
});

describe('PersonOverviewComponent', () => {
    let service: jasmine.SpyObj<PersonRelationsService>;
    let notifier: jasmine.SpyObj<ObjectChangeNotifierService>;
    let canEdit: boolean;

    function create(publicId: number, specialType: SpecialType): PersonOverviewComponent {
        const component = TestBed.runInInjectionContext(() => new PersonOverviewComponent());
        component.publicId = publicId;
        component.specialType = specialType;
        component.ngOnChanges({ publicId: new SimpleChange(undefined, publicId, true) });
        return component;
    }

    beforeEach(() => {
        canEdit = true;
        service = jasmine.createSpyObj<PersonRelationsService>('PersonRelationsService',
            ['getRelations', 'getCandidates', 'addMember', 'removeMember']);
        notifier = jasmine.createSpyObj<ObjectChangeNotifierService>('ObjectChangeNotifierService', ['notifyChanged']);
        const permissions = jasmine.createSpyObj<PermissionService>('PermissionService', ['hasRight', 'hasExtendedRight']);
        permissions.hasRight.and.callFake(() => canEdit);
        permissions.hasExtendedRight.and.returnValue(false);

        TestBed.configureTestingModule({
            providers: [
                { provide: PersonRelationsService, useValue: service },
                { provide: ObjectChangeNotifierService, useValue: notifier },
                { provide: PermissionService, useValue: permissions },
                { provide: ToastService, useValue: jasmine.createSpyObj('ToastService', ['success', 'error']) }
            ]
        });
    });

    describe('person', () => {
        beforeEach(() => {
            service.getRelations.and.returnValue(of(relations({ memberships: [OPS] })));
            service.getCandidates.and.returnValue(of([OPS, DEV]));
        });

        it('lists the memberships and offers only the other groups', () => {
            const component = create(11, SpecialType.PERSON);

            expect(service.getCandidates).toHaveBeenCalledWith(PersonRefKind.PERSON_GROUP, true);
            expect(component.linked).toEqual([OPS]);
            expect(component.candidates).toEqual([DEV]);
        });

        it('adds the person to the picked group and reloads its own relations', () => {
            service.addMember.and.returnValue(of(relations({ ref_type: 'PERSON_GROUP', members: [ALICE] })));
            const component = create(11, SpecialType.PERSON);

            component.selectedGroupId = 22;
            component.addToGroup();

            expect(service.addMember).toHaveBeenCalledWith(22, 11);
            expect(service.getRelations).toHaveBeenCalledTimes(2);
            expect(notifier.notifyChanged).toHaveBeenCalledWith(22);
        });

        it('removes the person from the row group', () => {
            service.removeMember.and.returnValue(of(relations({ ref_type: 'PERSON_GROUP' })));
            const component = create(11, SpecialType.PERSON);

            component.removeLinked(OPS);

            expect(service.removeMember).toHaveBeenCalledWith(21, 11);
        });

        it('does not write without the edit right', () => {
            canEdit = false;
            const component = create(11, SpecialType.PERSON);

            component.removeLinked(OPS);

            expect(service.removeMember).not.toHaveBeenCalled();
            expect(service.getCandidates).not.toHaveBeenCalled();
        });
    });

    describe('person group', () => {
        beforeEach(() => {
            service.getRelations.and.returnValue(of(relations({ ref_type: 'PERSON_GROUP', members: [ALICE] })));
            service.getCandidates.and.returnValue(of([ALICE, BOB]));
        });

        it('adds the picked persons and takes the answered relations', () => {
            service.addMember.and.returnValue(of(relations({ ref_type: 'PERSON_GROUP', members: [ALICE, BOB] })));
            const component = create(21, SpecialType.PERSON_GROUP);

            expect(component.candidates).toEqual([BOB]);
            component.selectedPersonIds = [12];
            component.addPersons();

            expect(service.addMember).toHaveBeenCalledWith(21, 12);
            expect(component.linked).toEqual([ALICE, BOB]);
            expect(component.candidates).toEqual([]);
            expect(notifier.notifyChanged).toHaveBeenCalledWith(21);
        });

        it('removes the row person from the group', () => {
            service.removeMember.and.returnValue(of(relations({ ref_type: 'PERSON_GROUP' })));
            const component = create(21, SpecialType.PERSON_GROUP);

            component.removeLinked(ALICE);

            expect(service.removeMember).toHaveBeenCalledWith(21, 11);
        });
    });
});
