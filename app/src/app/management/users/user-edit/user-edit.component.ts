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
import { Component, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';

import { ReplaySubject, takeUntil } from 'rxjs';

import { UserService } from '../../services/user.service';
import { ToastService } from '../../../layout/toast/toast.service';
import { PermissionService } from '../../../modules/auth/services/permission.service';

import { UserFormComponent } from '../components/user-form/user-form.component';
import { Group } from '../../models/group';
import { User } from '../../models/user';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-user-edit',
    templateUrl: './user-edit.component.html',
    styleUrls: ['./user-edit.component.scss']
})
export class UserEditComponent implements OnInit, OnDestroy {

    // UserFormComponent for static inserting of parameters
    @ViewChild(UserFormComponent, { static: true }) userFormComponent: UserFormComponent;

    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    public user: User;

    // List of possible groups
    public groups: Array<Group> = [];

    // Group of user while loaded
    public userGroup: Group;

    // List of possible auth providers
    public providers: Array<any> = [];

    private typeEditRightName = 'base.framework.type.edit';
    public typeEditRight = this.permissionService.hasRight(this.typeEditRightName) ||
                           this.permissionService.hasExtendedRight(this.typeEditRightName);

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    constructor(
        private route: ActivatedRoute,
        private router: Router,
        private userService: UserService,
        private toastService: ToastService,
        private permissionService: PermissionService
    ) {
        this.user = this.route.snapshot.data.user as User;
        this.groups = this.route.snapshot.data.groups as Array<Group>;
        this.userGroup = this.groups.find(group => group.public_id === this.user.group_id);
        this.providers = this.route.snapshot.data.providers as Array<any>;
    }


    public ngOnInit(): void {
        this.userFormComponent.form.removeControl('password');
    }


    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    /**
     * Update an existing user.
     * Sends a PUT request with the modified user data.
     * Displays a success message and navigates to the user list on success.
     * Shows an error message if the update fails.
     *
     * @param user The updated user data
     */
    public save(user: User): void {
        const editUser = Object.assign(this.user, user);
        this.userService.putUser(this.user.public_id, editUser)
            .pipe(takeUntil(this.subscriber))
            .subscribe({
                next: (apiUser: User) => {
                    this.toastService.success(`User ${apiUser.user_name} was updated`);
                    this.router.navigate(['/', 'management', 'users']);
                },
                error: (err) => {
                    this.toastService.error(err?.error?.message);
                }
            });
    }
}