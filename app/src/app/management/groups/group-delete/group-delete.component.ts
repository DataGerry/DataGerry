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

import { Component, OnDestroy, OnInit } from '@angular/core';
import { Group, GroupUsage } from '../../models/group';
import { ActivatedRoute, Router } from '@angular/router';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { GroupService } from '../../services/group.service';
import { finalize, takeUntil } from 'rxjs/operators';
import { ReplaySubject } from 'rxjs';
import { ToastService } from '../../../layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';

@Component({
    selector: 'cmdb-group-delete',
    templateUrl: './group-delete.component.html',
    styleUrls: ['./group-delete.component.scss'],
    standalone: false
})
export class GroupDeleteComponent implements OnInit, OnDestroy {

  public group: Group;
  public groups: Array<Group> = [];
  public deleteForm: UntypedFormGroup;
  public usage: GroupUsage;

  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();
  public isLoading$ = this.loaderService.isLoading$;


  constructor(private route: ActivatedRoute, 
    private router: Router, 
    private groupService: GroupService,
    private toast: ToastService,
    private loaderService: LoaderService) {
    this.group = this.route.snapshot.data.group as Group;
    this.groups = this.route.snapshot.data.groups as Array<Group>;

    this.deleteForm = new UntypedFormGroup({
      deleteGroupAction: new UntypedFormControl('', Validators.required),
      deleteGroupOption: new UntypedFormControl(2)
    });
  }

  public ngOnInit(): void {
    this.loadUsage();
  }

  public get soleMembers(): number {
    return this.usage?.sole_members ?? 0;
  }

  /**
   * On group deletion
   */
  public delete() {
    if (this.usage && this.deleteForm.valid) {
      this.loaderService.show();
      const action = this.soleMembers > 0 ? this.deleteForm.get('deleteGroupAction').value : null;
      const groupID = action === 'MOVE' ? this.deleteForm.get('deleteGroupOption').value : undefined;
      this.groupService.deleteGroup(this.group.public_id, action, groupID).
        pipe(takeUntil(this.subscriber), finalize(() => this.loaderService.hide()))
        .subscribe({
          next: () => {
            this.toast.success(`Group ${this.group.label} was deleted`);
            this.router.navigate(['/', 'management', 'groups']);
          },
          error: (error) => {
            this.toast.error(error?.error?.message);
          }
        }
        );
    }
  }

  private loadUsage(): void {
    this.loaderService.show();
    this.groupService.getGroupUsage(this.group.public_id)
      .pipe(takeUntil(this.subscriber), finalize(() => this.loaderService.hide()))
      .subscribe({
        next: (usage: GroupUsage) => {
          this.usage = usage;
          if (usage.sole_members === 0) {
            this.deleteForm.get('deleteGroupAction').clearValidators();
            this.deleteForm.get('deleteGroupAction').updateValueAndValidity();
          }
        },
        error: () => {
          this.toast.error('The group usage could not be loaded.');
        }
      });
  }

  /**
   * Auto unsubscribe on component destroy.
   */
  public ngOnDestroy(): void {
    this.subscriber.next();
    this.subscriber.complete();
  }

}
