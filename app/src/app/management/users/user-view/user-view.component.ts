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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { Component, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { User } from '../../models/user';
import { UserService } from '../../services/user.service';
import { GroupService } from '../../services/group.service';
import { Group } from '../../models/group';
import { ReplaySubject, Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { FormGroup } from '@angular/forms';
import { UserFormComponent } from '../components/user-form/user-form.component';
import { ToastService } from '../../../layout/toast/toast.service';
import { NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';
import { UsersPasswdModalComponent } from '../modals/users-passwd-modal/users-passwd-modal.component';
import { environment } from 'src/environments/environment';

@Component({
    selector: 'cmdb-user-view',
    templateUrl: './user-view.component.html',
    styleUrls: ['./user-view.component.scss'],
    standalone: false
})
export class UserViewComponent implements OnInit, OnDestroy {

  @ViewChild(UserFormComponent, { static: true }) userFormComponent: UserFormComponent;
  private modalRef: NgbModalRef;
  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

  public userID: number;
  public user: User;
  public group: Group;
  isCloudMode = environment.cloudMode;

  constructor(private route: ActivatedRoute, public userService: UserService, public groupService: GroupService,
    private toastService: ToastService, private modalService: NgbModal) {
    this.user = this.route.snapshot.data.user as User;
    this.group = this.route.snapshot.data.group as Group;
  }

  /**
   * Update the current user's profile.
   * Sends a PUT request with the updated user data.
   * Displays a success message on success or an error message on failure.
   *
   * @param user The updated user data
   */
  public save(user: User): void {
    const editUser = Object.assign(this.user, user);
    this.userService.putUser(this.user.public_id, editUser)
      .pipe(takeUntil(this.subscriber))
      .subscribe({
        next: (apiUser: User) => {
          this.toastService.success('Your profile was updated!');
        },
        error: (err) => {
          this.toastService.error(err?.error?.message);
        }
      });
  }  


  public ngOnInit(): void {
    this.userFormComponent.usernameControl.disable();
    this.userFormComponent.form.removeControl('password');
    this.userFormComponent.form.removeControl('authenticator');
    this.userFormComponent.form.removeControl('group_id');
  }

  public ngOnDestroy(): void {
    if (this.modalRef) {
      this.modalRef.close();
    }
    this.subscriber?.next();
    this.subscriber?.complete();
  }

  public openPasswordModal() {
    this.modalRef = this.modalService.open(UsersPasswdModalComponent, { size: 'lg' });
    this.modalRef.componentInstance.user = this.user;
    this.modalRef.result.then(result => {
      if (typeof result === typeof this.user) {
        this.user = result;
      }
    });
  }

}
