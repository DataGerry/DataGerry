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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import {Component, inject, Input } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
/* -------------------------------------------------------------------------- */


@Component({
    selector: 'cmdb-locations-modal',
    templateUrl: './locations-modal.component.html',
    styleUrls: ['./locations-modal.component.scss'],
    standalone: false
})
export class LocationsModalComponent {
  @Input() title = 'Information';
  @Input() modalIcon = 'trash';
  @Input() deleteObjectsButton = 'Delete with sub objects';
  @Input() deleteChildrenButton = 'Remove locations from sub objects';
  @Input() cancelButton = 'Cancel';

  public readonly activeModal = inject(NgbActiveModal);

  /** The modal shell expects a Font Awesome class, callers pass a bare icon name. */
  public get iconClass(): string {
    return `fas fa-${this.modalIcon}`;
  }
}
