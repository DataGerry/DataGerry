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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { Component, Input } from '@angular/core';
import { UntypedFormGroup } from '@angular/forms';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { RenderResult } from '../../../models/cmdb-render';
import { CmdbMode } from '../../../modes.enum';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-object-preview-modal',
    templateUrl: './object-preview-modal.component.html',
    styleUrls: ['./object-preview-modal.component.scss'],
    standalone: false
})
export class ObjectPreviewModalComponent {

  @Input() renderResult: RenderResult;
  public mode = CmdbMode.View;
  public formGroupDummy: UntypedFormGroup;

  constructor(public activeModal: NgbActiveModal) {
    this.formGroupDummy = new UntypedFormGroup({});
  }

}
