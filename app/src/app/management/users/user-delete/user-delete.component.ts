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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

import { Component, OnDestroy } from '@angular/core';
import { User } from '../../models/user';
import { ActivatedRoute, Router } from '@angular/router';
import { ReplaySubject } from 'rxjs';
import { UserService } from '../../services/user.service';
import { takeUntil } from 'rxjs/operators';
import { ToastService } from '../../../layout/toast/toast.service';

@Component({
    selector: 'cmdb-user-delete',
    templateUrl: './user-delete.component.html',
    styleUrls: ['./user-delete.component.scss'],
    standalone: false
})
export class UserDeleteComponent implements OnDestroy {

  /**
   * Component un-subscriber.
   */
  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

  /**
   * Selected user
   */
  public user: User;

  constructor(private route: ActivatedRoute, private router: Router, private userService: UserService,
              private toastService: ToastService) {
    this.user = this.route.snapshot.data.user as User;
  }

  public ngOnDestroy(): void {
    this.subscriber?.next();
    this.subscriber?.complete();
  }

  /**
   * Delete the current user.
   * Shows a success message and navigates to the user list on success.
   * Displays an error message if the deletion fails.
   */
  public delete(): void {
    this.userService.deleteUser(this.user.public_id)
      .pipe(takeUntil(this.subscriber))
      .subscribe({
        next: (user: User) => {
          this.toastService.success(`User ${user.user_name} was deleted`);
          this.router.navigate(['/', 'management', 'users']);
        },
        error: (err) => {
          this.toastService.error(err?.error?.message);
        }
      });
  }  
}
