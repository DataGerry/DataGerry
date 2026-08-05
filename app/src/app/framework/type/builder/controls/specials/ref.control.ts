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

class ReferenceContent implements ControlsContent {

  helperText: string;
  name: string;
  placeholder: string;
  required: boolean;
  type: string;
  value: any;
  label: string;
  typeID: number | number[];

  public constructor() {
    this.type = 'ref';
    this.name = randomName(this.type);
    this.label = 'Ref';
  }

}

export class ReferenceControl extends ControlsCommon {

  public name: string = 'ref';
  public label: string  = 'Reference';
  public icon: string  = 'fas fa-retweet';
  public dndType: string = 'inputs';

  public content(): ReferenceContent {
    return new ReferenceContent();
  }

}


