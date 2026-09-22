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

import { Column, SortDirection } from 'src/app/layout/table/table.types';
import { PortRow } from '../../models/ports-overview.types';
import { PortsTableComponent } from './ports-table.component';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('PortsTableComponent', () => {
    let component: PortsTableComponent;

    const row = (publicId: number, cableConnectionId: number | null = null): PortRow =>
        ({ publicId, name: `Gi0/${ publicId }`, cableConnectionId } as PortRow);

    beforeEach(() => {
        TestBed.configureTestingModule({})
            .overrideComponent(PortsTableComponent, { set: { template: '' } });

        component = TestBed.createComponent(PortsTableComponent).componentInstance;
        component.rows = [row(1, 9720), row(2)];
        component.canEdit = true;
        component.canDelete = true;
        component.canDisconnect = true;
        component.onSelectedChange(component.rows);
    });

    describe('selecting rows', () => {
        it('is only offered while a bulk action is permitted', () => {
            expect(component.selectEnabled).toBeTrue();

            component.canEdit = false;
            component.canDelete = false;
            component.canDisconnect = false;

            expect(component.selectEnabled).toBeFalse();
        });

        it('drops the selection on a page change, which the table does silently', () => {
            component.onPageChange(2);

            expect(component.selectedCount).toBe(0);
        });

        it('drops the selection when the rows are read again', () => {
            component.ngOnChanges({ rows: new SimpleChange([], component.rows, false) });

            expect(component.selectedCount).toBe(0);
        });

        it('drops the selection on a sort change', () => {
            component.onSortChange({ name: 'name', order: SortDirection.ASCENDING });

            expect(component.selectedCount).toBe(0);
        });
    });

    describe('bulk actions', () => {
        it('hands the selection up for an edit', () => {
            const emitted: PortRow[][] = [];
            component.bulkEditPorts.subscribe((rows) => emitted.push(rows));

            component.onBulkEdit();

            expect(emitted).toEqual([component.rows]);
        });

        it('emits nothing without the right, even with rows ticked', () => {
            const emitted: PortRow[][] = [];
            component.bulkDeletePorts.subscribe((rows) => emitted.push(rows));
            component.canDelete = false;

            component.onBulkDelete();

            expect(emitted).toEqual([]);
        });

        it('hands only the cabled rows up for a disconnect', () => {
            const emitted: PortRow[][] = [];
            component.bulkDisconnectPorts.subscribe((rows) => emitted.push(rows));

            component.onBulkDisconnect();

            expect(emitted).toEqual([[component.rows[0]]]);
        });

        it('emits nothing when no ticked row carries a cable', () => {
            const emitted: PortRow[][] = [];
            component.bulkDisconnectPorts.subscribe((rows) => emitted.push(rows));
            component.onSelectedChange([row(2)]);

            component.onBulkDisconnect();

            expect(emitted).toEqual([]);
        });
    });


    describe('column visibility', () => {
        const columnNamed = (name: string): Column => component.columns.find((column) => column.name === name);

        beforeEach(() => {
            component.ngOnInit();
        });

        it('keeps a column the user hid out of sight when the column set is rebuilt', () => {
            const speed = columnNamed('speed');
            speed.hidden = true;
            component.onColumnVisibilityChange(speed);

            component.showInterfaceColumn = true;
            component.ngOnChanges({ showInterfaceColumn: new SimpleChange(false, true, false) });

            expect(columnNamed('speed').hidden).toBeTrue();
            expect(columnNamed('port_type').hidden).toBeFalse();
        });

        it('offers every column for a reset, including the hidden ones', () => {
            const speed = columnNamed('speed');
            speed.hidden = true;
            component.onColumnVisibilityChange(speed);

            expect(component.visibleColumns).toContain('speed');
        });

        it('forgets the hidden columns once the table reports a reset', () => {
            const speed = columnNamed('speed');
            speed.hidden = true;
            component.onColumnVisibilityChange(speed);
            component.onColumnVisibilityChange();

            component.showInterfaceColumn = true;
            component.ngOnChanges({ showInterfaceColumn: new SimpleChange(false, true, false) });

            expect(columnNamed('speed').hidden).toBeFalse();
        });
    });
});
