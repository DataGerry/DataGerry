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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, OnDestroy, OnInit } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup } from '@angular/forms';

import { finalize, ReplaySubject, takeUntil } from 'rxjs';

import { GroupService } from '../../services/group.service';
import { ToastService } from '../../../layout/toast/toast.service';

import { Group } from '../../models/group';
import { CollectionParameters } from '../../../services/models/api-parameter';
import { APIGetMultiResponse } from '../../../services/models/api-response';
import { LoaderService } from 'src/app/core/services/loader.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-group-acl',
    templateUrl: './group-acl.component.html',
    styleUrls: ['./group-acl.component.scss']
})
export class GroupAclComponent implements OnInit, OnDestroy {

    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    // Group form selector
    public objectsACLGroupForm: UntypedFormGroup;

    // Chosen group
    public selectedGroup: Group;

    // Array of loaded cmdb groups
    public groups: Array<Group> = [];

    // Number of group pages
    private totalGroupPages: number;

    // Total number of groups
    public totalGroups: number;

    // ng-select loading indicator
    public groupsLoading: boolean = false;

    public groupParams: CollectionParameters = {
        filter: undefined, limit: 10, sort: 'public_id', order: 1, page: 1
    };

    public get groupControl(): UntypedFormControl {
        return this.objectsACLGroupForm.get('group') as UntypedFormControl;
    }

    public isLoading$ = this.loaderService.isLoading$;

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */
    constructor(private groupService: GroupService, private toast: ToastService, private loaderService: LoaderService) {
        this.objectsACLGroupForm = new UntypedFormGroup({
            group: new UntypedFormControl(undefined)
        });
    }


    public ngOnInit(): void {
        this.groupsLoading = true;
        this.loaderService.show();
        this.groupService.getGroups(this.groupParams).pipe(takeUntil(this.subscriber), finalize(() => this.loaderService.hide()))
            .subscribe({
                next: (apiResponse: APIGetMultiResponse<Group>) => {
                    this.groups = apiResponse.results as Array<Group>;
                    this.totalGroups = apiResponse.total;
                    this.totalGroupPages = apiResponse.pager.total_pages;
                    this.groupsLoading = false;
                },
                error: (err) => this.toast.error(err)
            }
        ).add(() => this.groupsLoading = false);

        this.groupControl.valueChanges.pipe(takeUntil(this.subscriber)).subscribe((group: Group) => {
            this.selectedGroup = group;
        });
    }


    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
    }

/* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

    /**
     * Load the groups from backend
     */
    private loadGroupsFromAPI() {
        this.loaderService.show();
        this.groupsLoading = true;
        this.groupService.getGroups(this.groupParams).pipe(takeUntil(this.subscriber), finalize(() => this.loaderService.hide()))
            .subscribe({
                next:(apiResponse: APIGetMultiResponse<Group>) => {
                    this.groups = this.groups.concat(apiResponse.results as Array<Group>);
                    this.groupsLoading = false;
                },
                error: (err) => this.toast.error(err)
            }
        ).add(() => this.groupsLoading = false);
    }


    /**
     * Load more groups until end of list is reached
     */
    public onScrollToEnd() {
        if (this.groupParams.page < this.totalGroupPages) {
        this.groupParams.page += 1;
        this.loadGroupsFromAPI();
        }
    }
}