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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { RenderFieldComponent } from '../components.fields';

@Component({
    templateUrl: './password.component.html',
    styleUrls: ['./text.component.scss'],
    standalone: false
})
export class PasswordComponent extends RenderFieldComponent implements OnInit {

  @ViewChild('passWordInput') public passWordToggle: ElementRef;

  public displayType: string = 'text';

  public constructor() {
    super();
  }

  public ngOnInit(): void {
    if (this.data.hasOwnProperty('force_hidden') && this.data.force_hidden) {
      this.displayType = 'password';
    }
  }

  public toggleInput() {
    if (this.passWordToggle.nativeElement.type === 'password') {
      this.passWordToggle.nativeElement.type = 'text';
    } else {
      this.passWordToggle.nativeElement.type = 'password';
    }
  }

  public generatePassword() {
    this.passWordToggle.nativeElement.value = Math.random().toString(36).slice(-8);
    this.controller.setValue(this.passWordToggle.nativeElement.value);
  }


}
