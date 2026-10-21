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

import { ControlsCommon, ControlsContent, randomName } from '../controls.common';

class PasswordContent implements ControlsContent {

  helperText: string;
  name: string;
  placeholder: string;
  required: boolean;
  type: string;
  value: any;
  label: string;

  public constructor() {
    this.type = 'password';
    this.name = randomName(this.type);
    this.label = 'Password Field';
  }

}

export class PasswordControl extends ControlsCommon {

  public name: string = 'password';
  public label: string = 'Password';
  public icon: string = 'fas fa-lock';
  public dndType: string = 'inputs';

  public content(): PasswordContent {
    return new PasswordContent();
  }

}

