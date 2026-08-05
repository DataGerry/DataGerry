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


  /**
   * Generates a secure random password with 16 characters including:
   * - Uppercase letters
   * - Lowercase letters
   * - Numbers
   * - Special characters
   * @returns void
   */
  public generatePassword(): void {
    const length = 16;
    const charset = "abcdefghijklmnopqrstuvwxyz" +
      "ABCDEFGHIJKLMNOPQRSTUVWXYZ" +
      "0123456789" +
      "!@#$%^&*()_+[]{}|;:,.<>?";

    let password = "";
    const charsetLength = charset.length;

    for (let i = 0; i < length; i++) {
      // Use rejection sampling to avoid modulo bias
      let randomValue;
      do {
        randomValue = window.crypto.getRandomValues(new Uint32Array(1))[0];
      } while (randomValue >= Math.floor(0x100000000 / charsetLength) * charsetLength);

      const randomIndex = randomValue % charsetLength;
      password += charset.charAt(randomIndex);
    }

    // Ensure password contains at least one character from each category
    const hasLower = /[a-z]/.test(password);
    const hasUpper = /[A-Z]/.test(password);
    const hasDigit = /[0-9]/.test(password);
    const hasSpecial = /[!@#$%^&*()_+\[\]{}|;:,.<>?]/.test(password);

    // If missing any category, regenerate (very rare with 16 chars)
    if (!hasLower || !hasUpper || !hasDigit || !hasSpecial) {
      this.generatePassword();
      return;
    }

    this.passWordToggle.nativeElement.value = password;
    this.controller.setValue(password);
  }
}
