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

import { Component, ElementRef, Input, ViewChild } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { User } from '../../../models/user';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { UserService } from '../../../services/user.service';
import { ToastService } from '../../../../layout/toast/toast.service';

@Component({
    templateUrl: './users-passwd-modal.component.html',
    styleUrls: ['./users-passwd-modal.component.scss'],
    standalone: false
})
export class UsersPasswdModalComponent {

  @ViewChild('passWordInput') public passWordToggle: ElementRef;
  @Input() public user: User;

  public passwdForm: UntypedFormGroup;

  constructor(private userService: UserService, public activeModal: NgbActiveModal, private toast: ToastService) {
    this.passwdForm = new UntypedFormGroup({
      public_id: new UntypedFormControl(null),
      password: new UntypedFormControl('', Validators.required)
    });
  }

  public get password() {
    return this.passwdForm.get('password');
  }

  public toggleInput() {
    if (this.passWordToggle.nativeElement.type === 'password') {
      this.passWordToggle.nativeElement.type = 'text';
    } else {
      this.passWordToggle.nativeElement.type = 'password';
    }
  }

  public onPasswordChange(): void {
    if (this.passwdForm.valid) {
      const changePasswd = this.userService.changeUserPassword(
        this.user.public_id, this.passwdForm.get('password').value).subscribe(
        (user: User) => {
          this.toast.success(`Password for user with ID: ${ this.user.public_id } was changed`);
          this.activeModal.close(user);
          changePasswd.unsubscribe();
        }
      );
    }
  }

}
