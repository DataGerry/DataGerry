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
import { Injectable, inject } from '@angular/core';

import { Observable, catchError, of } from 'rxjs';

import { TableService } from 'src/app/layout/table/table.service';
import { TableStatePayload } from 'src/app/layout/table/table.types';
import { convertResourceURL } from 'src/app/management/user-settings/services/user-settings.service';
import { PortsTableStateKey } from '../models/ports-table-state.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Reads the saved column views of a ports table. The shared table writes them. */
@Injectable({
    providedIn: 'root'
})
export class PortsTableStateService {

    private readonly tableService = inject(TableService);

    /** Emits `undefined` while no view was saved yet, which is not a failure. */
    public getStatePayload(key: PortsTableStateKey): Observable<TableStatePayload | undefined> {
        return this.tableService.getTableStatePayload(convertResourceURL(key.stateUrl), key.payloadId)
            .pipe(catchError(() => of(undefined)));
    }
}
