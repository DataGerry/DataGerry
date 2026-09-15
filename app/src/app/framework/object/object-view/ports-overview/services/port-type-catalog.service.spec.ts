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

import { of, throwError } from 'rxjs';

import { SpecialType } from 'src/app/framework/models/special-type';
import { TypeService } from 'src/app/framework/services/type.service';

import { PortTypeCatalogService } from './port-type-catalog.service';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('PortTypeCatalogService', () => {

    let service: PortTypeCatalogService;
    let typeService: jasmine.SpyObj<TypeService>;

    beforeEach(() => {
        typeService = jasmine.createSpyObj<TypeService>('TypeService', ['getTypes']);
        typeService.getTypes.and.callFake((params: any) => of({
            results: params?.filter?.special_type === SpecialType.CABLE ? [{ public_id: 30 }] : [{ public_id: 20 }],
            total: 1,
            count: 1
        }) as any);

        TestBed.configureTestingModule({
            providers: [
                PortTypeCatalogService,
                { provide: TypeService, useValue: typeService }
            ]
        });

        service = TestBed.inject(PortTypeCatalogService);
    });

    it('asks only for the ids it maps, not for whole type documents', () => {
        service.portCapableTypeIds().subscribe();

        expect(typeService.getTypes).toHaveBeenCalledWith(
            jasmine.objectContaining({ filter: { uses_ports: true }, projection: { public_id: 1 } }));
    });

    it('reads each marker once, however many dialogs ask for it', () => {
        const answers: number[][] = [];

        service.portCapableTypeIds().subscribe((ids) => answers.push(ids));
        service.portCapableTypeIds().subscribe((ids) => answers.push(ids));
        service.cableTypeIds().subscribe((ids) => answers.push(ids));

        expect(typeService.getTypes).toHaveBeenCalledTimes(2);
        expect(answers).toEqual([[20], [20], [30]]);
    });

    it('does not keep a failed read, so the next dialog asks again', () => {
        typeService.getTypes.and.returnValue(throwError(() => new Error('denied')));
        service.cableTypeIds().subscribe({ error: () => undefined });

        typeService.getTypes.and.returnValue(of({ results: [{ public_id: 30 }], total: 1, count: 1 }) as any);
        let ids: number[] = [];
        service.cableTypeIds().subscribe((answer) => ids = answer);

        expect(ids).toEqual([30]);
    });

    it('drops the cache when a type marker was changed', () => {
        service.cableTypeIds().subscribe();
        service.invalidate();
        service.cableTypeIds().subscribe();

        expect(typeService.getTypes).toHaveBeenCalledTimes(2);
    });
});
