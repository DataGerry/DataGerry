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

import { Component, Input, OnDestroy } from '@angular/core';
import { Group } from '../../../models/group';
import { GroupService } from '../../../services/group.service';
import { ReplaySubject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

@Component({
  selector: 'cmdb-user-table-group-cell',
  templateUrl: './user-table-group-cell.component.html',
  styleUrls: ['./user-table-group-cell.component.scss']
})
export class UserTableGroupCellComponent implements OnDestroy {

  /**
   * Component un-subscriber.
   * @private
   */
  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

  /**
   * List of a loaded groups.
   */
  @Input() public groups: Array<Group> = [];

  /**
   * Selected groupID.
   */
  public groupID: number;

  /**
   * Lazy loaded group.
   */
  @Input() public group: Group;

  /**
   * Is the group currently loading.
   */
  @Input() public groupLoadingStack: Array<number> = [];

  @Input('groupID')
  public set GroupID(groupID: number) {
    this.groupID = groupID;
    if (!this.groups.some(g => g.public_id === groupID)) {
      if (!this.groupLoadingStack.includes(groupID)) {
        this.groupLoadingStack.push(groupID);
        this.groupService.getGroup(this.groupID).pipe(takeUntil(this.subscriber)).subscribe((group: Group) => {
          this.groups.push(group);
        });
      }
    }
  }

  constructor(private groupService: GroupService) {
  }


  public ngOnDestroy(): void {
    this.subscriber?.next();
    this.subscriber?.complete();
  }

}
