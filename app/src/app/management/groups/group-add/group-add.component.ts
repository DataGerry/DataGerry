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

import { Component, OnDestroy, OnInit } from '@angular/core';
import { GroupService } from '../../services/group.service';
import { ActivatedRoute, Router } from '@angular/router';
import { Right } from '../../models/right';
import { Group } from '../../models/group';
import { finalize, takeUntil } from 'rxjs/operators';
import { ReplaySubject } from 'rxjs';
import { ToastService } from '../../../layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';

@Component({
  selector: 'cmdb-group-add',
  templateUrl: './group-add.component.html',
  styleUrls: ['./group-add.component.scss']
})
export class GroupAddComponent implements OnDestroy {

  public rights: Array<Right> = [];
  public valid: boolean = false;
  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();
  public isLoading$ = this.loaderService.isLoading$;

  constructor(private route: ActivatedRoute,
              private router: Router, private toastService: ToastService,
              private groupService: GroupService,
              private loaderService: LoaderService) {
    this.rights = this.route.snapshot.data.rights as Array<Right>;
  }

  /**
   * Call group api call.
   * @param group data
   */
  public save(group: Group) {
    if (this.valid) {
      this.loaderService.show();
      this.groupService.postGroup(group).pipe(takeUntil(this.subscriber), finalize(() => this.loaderService.hide()))
        .subscribe({
          next: (g: Group) => {
            this.toastService.success(`Group ${g.label} was added!`);
            this.router.navigate(['/', 'management', 'groups']);
          },
          error: (error) => {
            this.toastService.error(error?.error?.message);
          }
        }
        );
    }
  }

  /**
   * Auto unsubscribe on component destroy.
   */
  public ngOnDestroy(): void {
    this.subscriber?.next();
    this.subscriber?.complete();
  }

}
