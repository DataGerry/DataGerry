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
import { ChangeDetectorRef, Component, ElementRef, OnDestroy, OnInit, Renderer2 } from '@angular/core';
import { UntypedFormControl } from '@angular/forms';

import { ReplaySubject, Subscription, takeUntil } from 'rxjs';

import { TypeService } from '../../../framework/services/type.service';
import { SidebarService } from '../../services/sidebar.service';
import { UserService } from '../../../management/services/user.service';

import { User } from '../../../management/models/user';
import { CmdbCategoryTree } from '../../../framework/models/cmdb-category';
import { CmdbType } from '../../../framework/models/cmdb-type';
import { APIGetMultiResponse } from '../../../services/models/api-response';
import { CollectionParameters } from '../../../services/models/api-parameter';
import { AccessControlPermission } from 'src/app/modules/acl/acl.types';
import { LicenseFeature } from 'src/app/settings/license-management/models/license.model';
import { PremiumFeatureService } from 'src/app/settings/license-management/premium-feature/premium-feature.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-sidebar',
    templateUrl: './sidebar.component.html',
    styleUrls: ['./sidebar.component.scss'],
    standalone: false
})
export class SidebarComponent implements OnInit, OnDestroy {

    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    user: User;

    //Category data
    public categoryTree: CmdbCategoryTree;
    private categoryTreeSubscription: Subscription;

    //Types params
    public typesParams: CollectionParameters = {
        filter: undefined, limit: 0, sort: 'public_id', order: 1, page: 1
    };

    //Type data
    public typeList: CmdbType[] = [];
    public unCategorizedTypes: CmdbType[] = [];
    private unCategorizedTypesSubscription: Subscription;

    //Filter
    public filterTerm: UntypedFormControl = new UntypedFormControl('');
    private filterTermSubscription: Subscription;

    // String representation of currently selected tab menu in sidebar (Default is Categories)
    selectedMenu: string;

    // Sidebar expansion state
    isExpanded: boolean = false;
    isSidebarCollapsed: boolean = false;

    flyout: { group: string; top: number } | null = null;
    flyoutHovered = false;
<<<<<<< HEAD
=======

    // Whether IPAM is unlocked for the active edition; gates the "Networks" tab and the network tree.
    public ipamAvailable = false;
>>>>>>> origin/version-3.2

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(
        private sidebarService: SidebarService,
        private typeService: TypeService,
        private renderer: Renderer2,
        private elementRef: ElementRef,
        private userService: UserService,
        private cdRed: ChangeDetectorRef,
        private premiumFeatureService: PremiumFeatureService
    ) {
        this.categoryTreeSubscription = new Subscription();
        this.unCategorizedTypesSubscription = new Subscription();
        this.filterTermSubscription = new Subscription();
        this.user = this.userService.getCurrentUser();
    }


    public ngOnInit(): void {
        this.renderer.addClass(document.body, 'sidebar-fixed');

        this.isSidebarCollapsed = false; // default state

        if (this.user) {
            this.sidebarService.loadCategoryTree();
            this.categoryTreeSubscription = this.sidebarService.categoryTree.asObservable()
                .subscribe((categoryTree: CmdbCategoryTree) => {
                    this.categoryTree = categoryTree;

                    this.unCategorizedTypesSubscription = this.typeService.getUncategorizedTypes(AccessControlPermission.READ, false)
                        .subscribe((apiResponse: APIGetMultiResponse<CmdbType>) => {
                            this.unCategorizedTypes = apiResponse.results as Array<CmdbType>;
                            this.cdRed.detectChanges();
                        });

                    this.typeService.getTypes(this.typesParams).pipe(takeUntil(this.subscriber))
                        .subscribe((apiResponse: APIGetMultiResponse<CmdbType>) => {
                            this.typeList = apiResponse.results as Array<CmdbType>;
                        });
                });
        }

        this.selectedMenu = this.sidebarService.selectedMenu;

        this.premiumFeatureService.isAvailable$(LicenseFeature.Ipam)
            .pipe(takeUntil(this.subscriber))
            .subscribe((available) => {
                this.ipamAvailable = available;
                this.cdRed.markForCheck();
            });
    }


    public ngOnDestroy(): void {
        this.clearFlyoutCloseTimeout();
    
        this.subscriber?.next();
        this.subscriber?.complete();
    
        this.categoryTreeSubscription?.unsubscribe();
        this.unCategorizedTypesSubscription?.unsubscribe();
        this.filterTermSubscription?.unsubscribe();
    
        this.renderer?.removeClass(document?.body, 'sidebar-fixed');
    }

    /* ------------------------------------------------ SIDEBAR HANDLING ------------------------------------------------ */

    /**
     * Whether the "Navigation View" top tab is active (either of its nested sub-tabs is selected).
     */
    get isNavigationView(): boolean {
        return this.selectedMenu === 'locations' || this.selectedMenu === 'ipam';
    }


    /**
     * Selects a top-level tab. Entering "Navigation View" defaults to the Locations sub-tab,
     * but preserves the last-used sub-tab when already inside the navigation view.
     *
     * @param tab the top-level tab to activate
     */
    selectTopTab(tab: 'categories' | 'navigation'): void {
        if (tab === 'categories') {
            this.setMenu('categories');
            return;
        }

        if (!this.isNavigationView) {
            this.setMenu('locations');
        }
    }


    /**
     * Selects a nested tab inside the "Navigation View".
     *
     * @param tab the nested tab to activate
     */
    selectNavTab(tab: 'locations' | 'ipam'): void {
        this.setMenu(tab);
    }


    /** Opens the IPAM upgrade showcase from the locked network area. */
    promptIpamUpgrade(): void {
        this.premiumFeatureService.promptUpgrade(LicenseFeature.Ipam);
    }


    private setMenu(menu: string): void {
        this.selectedMenu = menu;
        this.sidebarService.selectedMenu = menu;
    }


    /**
     * Toggle the expansion state of the sidebar and dynamically update its width and related styles.
     * This function is called when the user clicks on the expand/collapse button.
     */
    public onExpandClicked() {
        // Toggle the expansion state
        this.isExpanded = !this.isExpanded;
        
        // Trigger change detection to update the view
        this.cdRed.markForCheck();
        
        // Dynamically set the width of the sidebar
        const newWidth = this.isExpanded ? '500px' : '230px';
        this.setSidebarWidth(newWidth);
        this.updateDynamicStyles(newWidth);
    }



    private setSidebarWidth(newWidth: string) {
        const sidebar = this.elementRef.nativeElement.querySelector('#sidebar');
        this.renderer.setStyle(sidebar, 'width', newWidth);
    }


    private updateDynamicStyles(newWidth: string) {
        const styles = `
        .sidebar-fixed #main {
            margin-left: ${newWidth};
            margin-top: $navbar-height;
        }
    
        @media (max-width: 767.98px) {
            .sidebar-fixed #main {
            margin-left: 0;
            }
        }
        `;

        let styleElement = document.getElementById('custom-styles') as HTMLStyleElement;

        if (!styleElement) {
            styleElement = document.createElement('style');
            styleElement.id = 'custom-styles';
            document.head.appendChild(styleElement);
        }

        styleElement.textContent = styles;
        const main = this.elementRef.nativeElement.querySelector('.sidebar-fixed #main');

        if (main) {
            this.renderer.setStyle(main, 'margin-left', newWidth);
        }
    }


    toggleSidebar(): void {
        this.isSidebarCollapsed = !this.isSidebarCollapsed;
        this.cdRed.markForCheck();
<<<<<<< HEAD
        const w = this.isSidebarCollapsed ? '64px' : '240px';
        this.setSidebarWidth(w);
        this.updateDynamicStyles(w);
    }

    onGroupMouseEnter(group: string, event: MouseEvent): void {
        if (!this.isSidebarCollapsed) { return; }
        const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
        this.flyout = { group, top: rect.top };
        this.cdRed.markForCheck();
    }

    onGroupMouseLeave(): void {
        setTimeout(() => {
=======
        const w = this.isSidebarCollapsed ? '75px' : '230px';
        this.setSidebarWidth(w);
        this.updateDynamicStyles(w);
    }
    
    private flyoutCloseTimeout: ReturnType<typeof setTimeout> | null = null;
    
    private clearFlyoutCloseTimeout(): void {
        if (this.flyoutCloseTimeout) {
            clearTimeout(this.flyoutCloseTimeout);
            this.flyoutCloseTimeout = null;
        }
    }
    
    onGroupMouseEnter(group: string, event: MouseEvent): void {
        if (!this.isSidebarCollapsed) {
            return;
        }

        this.clearFlyoutCloseTimeout();
        this.flyoutHovered = false;
    
        const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    
        this.flyout = {
            group,
            top: rect.top
        };
    
        this.cdRed.markForCheck();
    }
    
    onGroupMouseLeave(): void {
        this.clearFlyoutCloseTimeout();
    
        this.flyoutCloseTimeout = setTimeout(() => {
>>>>>>> origin/version-3.2
            if (!this.flyoutHovered) {
                this.flyout = null;
                this.cdRed.markForCheck();
            }
<<<<<<< HEAD
        }, 80);
    }

    onFlyoutMouseEnter(): void { this.flyoutHovered = true; }

    onFlyoutMouseLeave(): void {
        this.flyoutHovered = false;
        this.flyout = null;
        this.cdRed.markForCheck();
=======
    
            this.flyoutCloseTimeout = null;
        }, 120);
    }
    
    onFlyoutMouseEnter(): void {
        this.clearFlyoutCloseTimeout();
        this.flyoutHovered = true;
    }
    
    onFlyoutMouseLeave(): void {
        this.flyoutHovered = false;
    
        this.clearFlyoutCloseTimeout();
    
        this.flyoutCloseTimeout = setTimeout(() => {
            this.flyout = null;
            this.cdRed.markForCheck();
            this.flyoutCloseTimeout = null;
        }, 80);
>>>>>>> origin/version-3.2
    }
}
