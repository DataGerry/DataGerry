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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Injectable } from '@angular/core';

import { BehaviorSubject, Observable, map } from 'rxjs';

import { GroupService } from '../../../management/services/group.service';
import { Right } from '../../../management/models/right';
/* ------------------------------------------------------------------------------------------------------------------ */

@Injectable({
    providedIn: 'root'
})
export class PermissionService {
    // Right storage
    private currentUserRightListSubject: BehaviorSubject<Right[]>;
    public currentUserRightList: Observable<Right[]>;

/* -------------------------------------------------- GETTER/SETTER ------------------------------------------------- */

    public get currentUserRights(): Right[] {
        if (this.currentUserRightListSubject.value == null) {
            return [];
        }

        return this.currentUserRightListSubject.value;
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    constructor(private groupService: GroupService) {
        this.currentUserRightListSubject = new BehaviorSubject<Right[]>(
            JSON.parse(localStorage.getItem('current-user-rights'))
        );

        this.currentUserRightList = this.currentUserRightListSubject.asObservable();
    }


    public storeUserRights(groupID: number) {
        return this.groupService.getGroup(groupID).pipe(map(
            group => {
                localStorage.setItem('current-user-rights', JSON.stringify(group.rights));
                this.currentUserRightListSubject.next(group.rights);
                return group;
            }
        ));
    }


    public clearUserRightStorage() {
        localStorage.removeItem('current-user-rights');
        this.currentUserRightListSubject.next(null);
    }


    public hasRight(rightName: string): boolean {
        return !!this.currentUserRights.find(right => right.name === rightName);
    }


    public hasExtendedRight(rightName: string): boolean {
        let status = false;
        rightName = rightName.substring(0, rightName.lastIndexOf('.'));

        if (this.hasRight(`${ rightName }.*`)) {
            status = true;
        } else {
            if (rightName === 'base') {
                return false;
            }
            status = this.hasExtendedRight(rightName);
        }

        return status;
    }
}