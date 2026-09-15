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

import { Component, inject, Input, OnDestroy } from '@angular/core';
import { Right } from '../../../models/right';
import { GroupService } from '../../../services/group.service';
import { takeUntil } from 'rxjs/operators';
import { ReplaySubject } from 'rxjs';
import { GroupUsersModalComponent } from '../../../groups/modals/group-users-modal/group-users-modal.component';
import { RightGroupsModalComponent } from '../../modals/right-groups-modal/right-groups-modal.component';
import { NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';

@Component({
    selector: 'cmdb-right-table-groups-cell',
    templateUrl: './right-table-groups-cell.component.html',
    styleUrls: ['./right-table-groups-cell.component.scss'],
    standalone: false
})
export class RightTableGroupsCellComponent implements OnDestroy {

  /**
   * Component un-subscriber.
   * @private
   */
  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

  /**
   * Global modal reference.
   * @private
   */
  private modalRef: NgbModalRef;

  /**
   * Right in this mod.
   */
  public right: Right;
  public numberOfGroups: number;

  @Input('right')
  public set Right(r: Right) {
    this.right = r;
    this.groupService.countGroups({ rights: this.right.name }).pipe(takeUntil(this.subscriber))
      .subscribe((nGroups: number) => {
        this.numberOfGroups = nGroups;
      });
  }

  private readonly groupService = inject(GroupService);
  private readonly modalService = inject(NgbModal);

  public openGroupListModal(): void {
    this.modalRef = this.modalService.open(RightGroupsModalComponent, {
      size: 'lg',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    this.modalRef.componentInstance.right = this.right;
  }

  public ngOnDestroy(): void {
    if (this.modalRef) {
      this.modalRef.close();
    }
    this.subscriber?.next();
    this.subscriber?.complete();
  }

}
