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

import { ChangeDetectionStrategy, Component, inject, input, OnDestroy } from '@angular/core';
import { NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';

import { RightOverview } from '../../../models/right';
import { RightGroupsModalComponent } from '../../modals/right-groups-modal/right-groups-modal.component';

@Component({
    selector: 'cmdb-right-table-groups-cell',
    templateUrl: './right-table-groups-cell.component.html',
    styleUrls: ['./right-table-groups-cell.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class RightTableGroupsCellComponent implements OnDestroy {

  public readonly right = input.required<RightOverview>();

  private readonly modalService = inject(NgbModal);

  /**
   * Global modal reference.
   * @private
   */
  private modalRef: NgbModalRef;

  public openGroupListModal(): void {
    this.modalRef = this.modalService.open(RightGroupsModalComponent, {
      size: 'lg',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    this.modalRef.componentInstance.right = this.right();
  }

  public ngOnDestroy(): void {
    this.modalRef?.close();
  }

}
