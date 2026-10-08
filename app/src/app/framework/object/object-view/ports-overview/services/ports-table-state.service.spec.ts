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

import { TableService } from 'src/app/layout/table/table.service';
import { TableStatePayload } from 'src/app/layout/table/table.types';
import { PATCH_PANEL_TABLE_STATE, STANDARD_PORTS_TABLE_STATE } from '../models/ports-table-state.types';
import { PortsTableStateService } from './ports-table-state.service';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('PortsTableStateService', () => {
    let service: PortsTableStateService;
    let tableService: jasmine.SpyObj<TableService>;

    beforeEach(() => {
        tableService = jasmine.createSpyObj<TableService>('TableService', ['getTableStatePayload']);

        TestBed.configureTestingModule({
            providers: [{ provide: TableService, useValue: tableService }]
        });

        service = TestBed.inject(PortsTableStateService);
    });

    it('reads the standard table from its own setting', () => {
        tableService.getTableStatePayload.and.returnValue(of(undefined));

        service.getStatePayload(STANDARD_PORTS_TABLE_STATE).subscribe();

        expect(tableService.getTableStatePayload)
            .toHaveBeenCalledWith('framework-object-ports-standard', 'object-ports-table');
    });

    it('reads the patch panel table from its own setting', () => {
        tableService.getTableStatePayload.and.returnValue(of(undefined));

        service.getStatePayload(PATCH_PANEL_TABLE_STATE).subscribe();

        expect(tableService.getTableStatePayload)
            .toHaveBeenCalledWith('framework-object-ports-patch-panel', 'object-patch-panel-table');
    });

    it('hands the stored views on', () => {
        const payload = new TableStatePayload('object-ports-table', [{ name: 'Compact', visibleColumns: ['name'] }]);
        tableService.getTableStatePayload.and.returnValue(of(payload));
        let result: TableStatePayload | undefined;

        service.getStatePayload(STANDARD_PORTS_TABLE_STATE).subscribe((value) => result = value);

        expect(result).toBe(payload);
    });

    it('answers a setting that does not exist yet with undefined', () => {
        tableService.getTableStatePayload.and.returnValue(throwError(() => new TypeError('setting is undefined')));
        let result: TableStatePayload | undefined = new TableStatePayload('object-ports-table', []);

        service.getStatePayload(STANDARD_PORTS_TABLE_STATE).subscribe((value) => result = value);

        expect(result).toBeUndefined();
    });
});
