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

import { Component, EventEmitter, Input, OnChanges, OnDestroy, OnInit, Output, SimpleChanges } from '@angular/core';
import { User } from '../../../models/user';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { Group } from '../../../models/group';
import { takeUntil } from 'rxjs/operators';
import { ReplaySubject } from 'rxjs';
import { Right } from '../../../models/right';
import { environment } from 'src/environments/environment';

@Component({
  selector: 'cmdb-user-form',
  templateUrl: './user-form.component.html',
  styleUrls: ['./user-form.component.scss']
})
export class UserFormComponent implements OnInit, OnChanges, OnDestroy {

  public isCloudMode: boolean;

  /**
   * Component un-subscriber.
   */
  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

  /**
   * Input if user data exists.
   */
  @Input() public user: User;

  /**
   * List of possible groups.
   */
  @Input() public groups: Array<Group> = [];

  /**
   * List of possible auth providers.
   */
  @Input() public providers: Array<any> = [];

  /**
   * User NgForm.
   */
  public form: UntypedFormGroup;

  /**
   * Output if submit was triggered.
   */
  @Output() public submit: EventEmitter<User> = new EventEmitter<User>();

  /**
   * Output if validation status was changed.
   */
  @Output() public validation: EventEmitter<string> = new EventEmitter<string>();

  @Input() cancel: boolean = true;

  public preview: any = undefined;

  constructor() {

    this.isCloudMode = environment.cloudMode;


    this.form = new UntypedFormGroup({
      user_name: new UntypedFormControl('', [Validators.required]),
      email: new UntypedFormControl('', [Validators.email]),
      password: new UntypedFormControl('', [Validators.required]),
      first_name: new UntypedFormControl(null),
      last_name: new UntypedFormControl(null),
      authenticator: new UntypedFormControl('LocalAuthenticationProvider', Validators.required),
      group_id: new UntypedFormControl(2, Validators.required),
      image: new UntypedFormControl(null)
    });
  }

  public ngOnInit(): void {

    if (this.isCloudMode) {
      this.form.disable(); // Ensure the form is disabled
    }

    this.form.statusChanges.pipe(takeUntil(this.subscriber)).subscribe(status => {
      this.validation.emit(status);
    });
  }

  public get usernameControl(): UntypedFormControl {
    return this.form.get('user_name') as UntypedFormControl;
  }

  public get emailControl(): UntypedFormControl {
    return this.form.get('email') as UntypedFormControl;
  }

  public get passwordControl(): UntypedFormControl {
    return this.form.get('password') as UntypedFormControl;
  }

  public get firstNameControl() {
    return this.form.get('first_name') as UntypedFormControl;
  }

  public get lastNameControl() {
    return this.form.get('last_name') as UntypedFormControl;
  }

  public get authenticatorControl() {
    return this.form.get('authenticator') as UntypedFormControl;
  }

  public get groupControl() {
    return this.form.get('group_id') as UntypedFormControl;
  }

  public get imageControl() {
    return this.form.get('image') as UntypedFormControl;
  }

  public previewImage(event) {
    if (event.target.files && event.target.files[0]) {
      const reader = new FileReader();
      reader.onload = (eve: ProgressEvent) => {
        this.preview = (eve.target as FileReader).result;
        this.imageControl.setValue(this.preview);
      };
      reader.readAsDataURL(event.target.files[0]);
    }
  }

  public removeImage() {
    this.imageControl.setValue(null);
    this.preview = null;
  }

  public onSubmit(): void {
    this.form.markAllAsTouched();
    if (this.form.valid) {
      this.submit.emit(this.form.value as User);
    }
  }

  /**
   * OnChange call for user form component.
   * Patches passed user data into the form.
   *
   * @param changes SimpleChanges of all input changes.
   */
  public ngOnChanges(changes: SimpleChanges): void {
    if (changes.user && changes.user.currentValue !== changes.user.previousValue) {
      this.form.patchValue(this.user);
      this.preview = this.user.image;
      this.form.markAllAsTouched();
    }
  }

  /**
   * Auto un-subscribe by component destroy.
   */
  public ngOnDestroy(): void {
    this.subscriber?.next();
    this.subscriber?.complete();
  }

}
