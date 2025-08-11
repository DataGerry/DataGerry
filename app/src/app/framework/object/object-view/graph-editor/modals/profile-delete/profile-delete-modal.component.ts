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
import { Component, Input } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { FilterProfile } from '../../interfaces/graph.interfaces';

@Component({
    selector: 'app-profile-delete-modal',
    templateUrl: './profile-delete-modal.component.html',
    styleUrls: ['./profile-delete-modal.component.scss'],
    standalone: false
})
export class ProfileDeleteModalComponent {
  @Input() public profile: FilterProfile;

  constructor(public activeModal: NgbActiveModal) {}

  /**
   * Closes the modal and confirms the deletion action.
   */
  confirmDelete(): void {
    this.activeModal.close(this.profile?.public_id);
  }
}