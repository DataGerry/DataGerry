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
import { Injectable } from '@angular/core';
import { Observable, Subject } from 'rxjs';
/* ------------------------------------------------------------------------------------------------------------------ */


/**
 * Announces that an object was written, for the views showing that same object.
 *
 * A view that writes an object it did not load - the rack view saves the rack's notes - has no way of
 * telling the page around it. Only the id is passed on: whoever is showing the object knows how to read
 * it, and reading it again is what keeps every card on the page honest rather than a value copied over.
 */
@Injectable({ providedIn: 'root' })
export class ObjectChangeNotifierService {

    private readonly changed = new Subject<number>();

    /** The public_id of an object that has just been written. */
    public readonly changed$: Observable<number> = this.changed.asObservable();

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** Called once the write has gone through; a refused write leaves the views showing what they had. */
    public notifyChanged(objectId: number): void {
        this.changed.next(objectId);
    }
}
