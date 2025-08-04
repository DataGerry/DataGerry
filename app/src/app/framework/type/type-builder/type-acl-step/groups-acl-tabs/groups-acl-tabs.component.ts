/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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
import { Component, EventEmitter, Input, OnDestroy, Output } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';

import { ReplaySubject } from 'rxjs';

import { AccessControlListSection, AccessControlPermission } from 'src/app/modules/acl/acl.types';
import { Group } from '../../../../../management/models/group';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-groups-acl-tabs',
    templateUrl: './groups-acl-tabs.component.html',
    styleUrls: ['./groups-acl-tabs.component.scss']
})
export class GroupsAclTabsComponent implements OnDestroy {

    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    // Event emitter when a value inside the form changes
    @Output() public valueChange: EventEmitter<any> = new EventEmitter<any>();

    @Input() public groups: Array<Group> = [];
    @Input() public form: UntypedFormGroup;

    public groupsACL: AccessControlListSection<number> = new AccessControlListSection<number>();
    public selectedGroup: Group;
    public selectedPermissions: Array<AccessControlPermission>;

    @Input('groupsACL')
    public set GroupsACL(groups: AccessControlListSection<number>) {
        if (groups) {
            this.groupsACL = groups;

            for (const entry in groups.includes) {
                this.addControl(entry);
            }

            this.form.patchValue(groups.includes);
        }
    }

    public readonly operations: Array<string> = Object.keys(AccessControlPermission);

    public get controls() {
        return this.form.controls;
    }

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    public getGroupLabelByID(publicID: number): string {
        const found = this.groups.find(g => g.public_id === publicID);

        if (found) {
            return found.label;
        }

        return `GroupID: ${ publicID } does not exist`;
    }


    /**
     * On html click event
     */
    public onAddControl(): void {
        if (this.selectedGroup) {
            const controlName = `${ this.selectedGroup.public_id }`;
            this.addControl(controlName);

            if (this.selectedPermissions) {
                this.form.get(controlName).setValue(this.selectedPermissions);
            }

            this.selectedGroup = undefined;
            this.selectedPermissions = undefined;
        }

        this.valueChange.emit([[], null]);
    }


    /**
     * Add a new acl entry
     */
    public addControl(name: number | string): void {
        const control = new UntypedFormControl([]);
        control.setValidators([Validators.required, Validators.minLength(1)]);
        this.form.addControl(`${ name }`, control);
    }


    /**
     * Remove a existing entry
     * @param name
     */
    public removeControl(name: string): void {
        this.form.removeControl(name);
    }
}