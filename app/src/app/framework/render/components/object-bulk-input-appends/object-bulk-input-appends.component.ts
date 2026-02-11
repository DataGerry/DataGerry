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

import { Component, Input, OnDestroy, OnInit } from '@angular/core';
import { BehaviorSubject, ReplaySubject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { AbstractControl, UntypedFormControl, UntypedFormGroup } from '@angular/forms';

@Component({
    selector: 'cmdb-object-bulk-input-appends',
    templateUrl: './object-bulk-input-appends.component.html',
    styleUrls: ['./object-bulk-input-appends.component.scss'],
    standalone: false
})
export class ObjectBulkInputAppendsComponent implements OnInit, OnDestroy {

  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

  @Input() public changeForm: UntypedFormGroup;
  @Input() public controller: UntypedFormControl;
  @Input() public data: any;

  public checkedSubject: BehaviorSubject<boolean> = new BehaviorSubject<boolean>(false);

  public ngOnInit(): void {
    this.controller.valueChanges.pipe(takeUntil(this.subscriber)).subscribe(() => {
      if (!this.checked) {
        this.checkedSubject.next(true);
      }
      this.changeForm.get(this.data.name).setValue(this.controller.value);
    });
    this.checkedSubject.asObservable().pipe(takeUntil(this.subscriber)).subscribe((checked: boolean) => {
      this.changeCheckBox(checked);
    });
  }

  public get checked(): boolean {
    return this.checkedSubject.value;
  }

  public changeCheckBox(checked: boolean) {
    if (checked) {
      this.changeForm.addControl(this.data.name, new UntypedFormControl(this.controller.value));
    } else {
      this.changeForm.removeControl(this.data.name);
    }
  }

  public onCheckChange(event: Event): void {
    this.checkedSubject.next((event.target as HTMLInputElement).checked);
  }

  public ngOnDestroy(): void {
    this.subscriber?.next();
    this.subscriber?.complete();
  }
}
