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

    isExpanded: boolean = false

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(
        private sidebarService: SidebarService,
        private typeService: TypeService,
        private renderer: Renderer2,
        private elementRef: ElementRef,
        private userService: UserService,
        private cdRed: ChangeDetectorRef
    ) {
        this.categoryTreeSubscription = new Subscription();
        this.unCategorizedTypesSubscription = new Subscription();
        this.filterTermSubscription = new Subscription();
        this.user = this.userService.getCurrentUser();
    }


    public ngOnInit(): void {
        this.renderer.addClass(document.body, 'sidebar-fixed');

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
    }


    public ngOnDestroy(): void {
        this.subscriber?.complete();
        this.categoryTreeSubscription?.unsubscribe();
        this.unCategorizedTypesSubscription?.unsubscribe();
        this.filterTermSubscription?.unsubscribe();
        this.renderer?.removeClass(document?.body, 'sidebar-fixed');
    }

    /* ------------------------------------------------ SIDEBAR HANDLING ------------------------------------------------ */

    /**
     * Toggles the activated menu tabs (categories and locations)
     * 
     * @param selection :string = String representation of the selected menu
     */
    onSidebarMenuClicked(selection: HTMLDivElement) {
        let newValue = selection.getAttribute('value');
        this.selectedMenu = newValue;
        this.sidebarService.selectedMenu = newValue;
    }


    /**
     * Toggle the expansion state of the sidebar and dynamically update its width and related styles.
     * This function is called when the user clicks on the expand/collapse button.
     */
    onExpandClicked() {

        // Toggle the expansion state
        this.isExpanded = !this.isExpanded;

        // Dynamically set the width of the sidebar
        const newWidth = this.isExpanded ? '500px' : '230px';
        this.setSidebarWidth(newWidth);

        // Update dynamic styles based on the new width
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
}