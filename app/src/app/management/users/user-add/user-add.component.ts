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
import { AfterViewInit, Component, OnDestroy, ViewChild } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';

import { ReplaySubject, takeUntil } from 'rxjs';

import { userExistsValidator, UserService } from '../../services/user.service';
import { ToastService } from '../../../layout/toast/toast.service';

import { Group } from '../../models/group';
import { UserFormComponent } from '../components/user-form/user-form.component';
import { User } from '../../models/user';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-user-add',
    templateUrl: './user-add.component.html',
    styleUrls: ['./user-add.component.scss'],
    standalone: false
})
export class UserAddComponent implements AfterViewInit, OnDestroy {

    // UserFormComponent for static inserting of parameters
    @ViewChild(UserFormComponent, { static: true }) userFormComponent: UserFormComponent;

    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    // List of possible groups
    public groups: Array<Group> = [];

    // List of possible auth providers
    public providers: Array<any> = [];

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    constructor(
        private route: ActivatedRoute,
        private router: Router,
        private userService: UserService,
        private toastService: ToastService
    ) {
        this.groups = this.route.snapshot.data.groups as Array<Group>;
        this.providers = this.route.snapshot.data.providers as Array<any>;
    }


    public ngAfterViewInit(): void {
        this.userFormComponent.usernameControl.setAsyncValidators(userExistsValidator(this.userService));
    }


    public ngOnDestroy(): void {
        this.subscriber.next();
        this.subscriber.complete();
    }

/* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

  /**
   * Save a new user.
   * Sends a POST request to create the user and navigates to the user list on success.
   * Displays an error message if the creation fails.
   *
   * @param user The user object to be created
   */
    public save(user: User): void {
        this.userService.postUser(user).pipe(takeUntil(this.subscriber)).subscribe({
            next: (apiUser: User) => {
                this.toastService.success(`User ${apiUser.user_name} was added`);
                this.router.navigate(['/', 'management', 'users']);
            },
            error: (err) => {
                this.toastService.error(err?.error?.message);
            }
        });
    }
}