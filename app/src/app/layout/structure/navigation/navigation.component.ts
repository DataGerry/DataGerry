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
import { Component, OnInit } from '@angular/core';

import * as jQuery from 'jquery';

import { AuthService } from '../../../modules/auth/services/auth.service';
import { UserService } from '../../../management/services/user.service';
import { GroupService } from '../../../management/services/group.service';

import { User } from '../../../management/models/user';
import { Group } from '../../../management/models/group';
import { ObjectService } from 'src/app/framework/services/object.service';
import { Observable, Subscription, switchMap } from 'rxjs';
import { environment } from '../../../../environments/environment';

import { Router } from '@angular/router';
import { NotificationQuery } from 'src/app/core/state/notification/notification.query';
/* ------------------------------------------------------------------------------------------------------------------ */

declare global {
    interface Window { ATL_JQ_PAGE_PROPS: any; }
}

window.ATL_JQ_PAGE_PROPS = window.ATL_JQ_PAGE_PROPS || {};

@Component({
    selector: 'cmdb-navigation',
    templateUrl: './navigation.component.html',
    styleUrls: ['./navigation.component.scss'],
    standalone: false
})
export class NavigationComponent implements OnInit {

    public user: User;
    public group: Group;

    public usedObjects: number = 0;
    public totalObjects: number = 0;
    public isCloudMode = environment.cloudMode;
    public featurePreviewMode = environment.featurePreviewMode;
    public isNotificationDrawerOpen = false;
    public readonly notificationCount$: Observable<number>;
    configItemsLimit: number;
    private subscription: Subscription;


    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(
        public authService: AuthService,
        private userService: UserService,
        private groupService: GroupService,
        private objectService: ObjectService,
        private router: Router,
        private notificationQuery: NotificationQuery
    ) {
        this.user = this.userService.getCurrentUser();
        this.notificationCount$ = this.notificationQuery.selectCount();
    }


    public ngOnInit(): void {
        if (this.user) {

            this.objectService.countObjects().pipe(
                switchMap(() => this.objectService.getLastObjectCount())
            ).subscribe(count => {
                this.usedObjects = count;
            });

            this.groupService.getGroup(this.user.group_id).subscribe(resp => {
                this.group = resp;
            });

            this.subscription = this.objectService.getConfigItemsLimit().subscribe({
                next: (limit) => {
                    this.totalObjects = limit;
                }
            });

        }

        this.dropdownSubmenu();
    }


    ngOnDestroy(): void {
        if (this.subscription) {
            this.subscription.unsubscribe();
        }
    }

    /* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

    /**
     * Logout the user via the menu in top right corner
     */
    public logout(): void {
        this.authService.logout();
    }


    private dropdownSubmenu() {
        $('.dropdown-menu a.dropdown-toggle').on('click', (e) => {
            if (!$(this).next().hasClass('show')) {
                $(this).parents('.dropdown-menu').first().find('.show').removeClass('show');
            }

            const $subMenu = $(this).next('.dropdown-menu');
            $subMenu.toggleClass('show');

            $(this).parents('li.nav-item.dropdown.show').on('hidden.bs.dropdown', () => {
                $('.dropdown-submenu .show').removeClass('show');
            });

            return false;
        });
    }


    public visibilitySidebar() {
        const sidebar = document.getElementById('sidebar').classList;
        sidebar.length === 0 ? sidebar.add('set-sidebar-visible') : sidebar.remove('set-sidebar-visible');
    }


    public feedback() {
        jQuery.ajax({
            url: "https://becon88.atlassian.net/s/d41d8cd98f00b204e9800998ecf8427e-T/6i46lu/b/8/b0105d975e9e59f24a3230a22972a71a/_/download/batch/com.atlassian.jira.collector.plugin.jira-issue-collector-plugin:issuecollector-embededjs/com.atlassian.jira.collector.plugin.jira-issue-collector-plugin:issuecollector-embededjs.js?locale=de-DE&collectorId=f2da5b6f",
            type: 'get',
            cache: true,
            dataType: 'script'
        });

        window.ATL_JQ_PAGE_PROPS = {
            "triggerFunction": function (showCollectorDialog) {
                showCollectorDialog();
            }
        };
    }


    /**
     * Open the DATAGERRY Assistant from the Toolbox
     */
    public openIntroModal() {
        this.authService.showIntro(true);
    }


    /**
     * Calculates the percentage of used objects relative to the total objects.
     * @returns A number representing the usage percentage.
     */
    get percentage(): number {
        return (this.usedObjects / this.totalObjects) * 100;
    }


    /**
     * Determines the color of the progress bar based on the usage percentage.
     * @returns A string representing the color of the progress bar.
     */
    getProgressBarColor(): string {
        if (this.percentage <= 50) {
            return 'green';
        } else if (this.percentage <= 85) {
            return 'rgb(255, 193, 7)';
        } else {
            return 'red';
        }
    }


    /**
     * Determines the text color for the percentage display based on the usage percentage.
     * @returns A string representing the text color in HEX format.
     */
    getTextColor(): string {
        return this.percentage > 85 ? '#fff' : '#000'; // Use white text on high usage (red background)
    }


    public goToAiPromptPage(): void {
        this.router.navigate(['/ai-assistant']);
    }


    public toggleNotificationDrawer(): void {
        this.isNotificationDrawerOpen = !this.isNotificationDrawerOpen;
    }

    
    public closeNotificationDrawer(): void {
        this.isNotificationDrawerOpen = false;
    }


    public formatNotificationCount(count: number | null): string {
        if (!count || count <= 0) {
            return '';
        }

        return count > 9 ? '9+' : `${count}`;
    }
}
