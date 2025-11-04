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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

import { Component, ElementRef, ViewChild } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';

@Component({
  selector: 'app-internal-connector-password-modal',
  templateUrl: './internal-connector-password-modal.component.html',
  styleUrls: ['./internal-connector-password-modal.component.scss'],
  standalone: false
})
export class InternalConnectorPasswordModalComponent {

  @ViewChild('passwordInput') public passwordInput: ElementRef;

  public passwordForm: UntypedFormGroup;
  public errorMessage: string = '';
  public isLoading: boolean = false;

  constructor(public activeModal: NgbActiveModal) {
    this.passwordForm = new UntypedFormGroup({
      password: new UntypedFormControl('', Validators.required)
    });
  }

  public get password() {
    return this.passwordForm.get('password');
  }

  public togglePasswordVisibility(): void {
    if (this.passwordInput.nativeElement.type === 'password') {
      this.passwordInput.nativeElement.type = 'text';
    } else {
      this.passwordInput.nativeElement.type = 'password';
    }
  }

  public onSubmit(): void {
    if (this.passwordForm.valid) {
      this.isLoading = true;
      this.errorMessage = '';
      this.activeModal.close(this.passwordForm.get('password').value);
    }
  }

  public onCancel(): void {
    this.activeModal.dismiss('cancel');
  }

  public setError(message: string): void {
    this.errorMessage = message;
    this.isLoading = false;
  }
}
