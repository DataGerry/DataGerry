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
import { Injectable } from '@angular/core';

import { BehaviorSubject } from 'rxjs';

import { UserService } from 'src/app/management/services/user.service';
import { ObjectService} from '../../framework/services/object.service';

import { User } from 'src/app/management/models/user';
import { CmdbCategoryTree } from '../../framework/models/cmdb-category';
import { CategoryService } from '../../framework/services/category.service';
import { SidebarTypeComponent } from '../structure/sidebar/sidebar-type.component';
/* -------------------------------------------------------------------------- */

@Injectable({
  providedIn: 'root'
})
export class SidebarService {

    /**
     * Basic tree observer
     */
    private categoryTreeObserver = new BehaviorSubject<CmdbCategoryTree>(new CmdbCategoryTree());
    private reloadData = new BehaviorSubject(false);
    private sideBarType: SidebarTypeComponent[] = [];

    user: User;

    /**
     * Used to track which tab was selected before reload
     */
    public selectedMenu: string = 'categories';

/* -------------------------------------------------- GETTER/SETTER ------------------------------------------------- */

    /**
     * Get the subject of the current category tree.
     */
    public get categoryTree(): BehaviorSubject<CmdbCategoryTree> {
        return this.categoryTreeObserver;
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    constructor(
        private categoryService: CategoryService,
        private objectService: ObjectService,
        private userService: UserService
    ) {
        this.user = this.userService.getCurrentUser();

        // if(this.user){
        //     this.loadCategoryTree();
        // }
    }

/* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

    /**
     * Load Category Tree {@link CmdbCategoryTree}.
     */
    public loadCategoryTree() {
        this.categoryService.getCategoryTree().subscribe((tree: CmdbCategoryTree)  => {
            this.categoryTreeObserver.next(tree);
        });
    }


    /**
     * gets the object count of the given type
     *
     * @param typeID: the type id of the type of which the objects are counted
     */
    private async getObjectCount(typeID): Promise<number> {
        return new Promise((resolve) => {
            this.objectService.countObjectsByType(typeID).subscribe((data: number) => {
                resolve(data);
            });
        });
    }


    /**
     * updates the objectCounter of the affected sidebar-type component
     *
     * @param typeID the type id with to the sidebar-typ component will be filtered
     */
    public async updateTypeCounter(typeID) {
        const sidebarType = this.sideBarType.filter(type => type.type.public_id === typeID).pop();

        if(sidebarType){
            await this.getObjectCount(sidebarType.type.public_id).then( count => {
                sidebarType.objectCounter = count;
            });
        } 
    }


    /**
     * inserts the sidebar-type component into an array and updates its counter
     *
     * @param sidebarType the sidebar-type component which will be inserted
     */
    public initializeCounter(sidebarType: SidebarTypeComponent) {
        this.reloadData.subscribe( () => { 
            this.sideBarType.push(sidebarType);
            this.updateTypeCounter(sidebarType.type.public_id);
        });
    }


    /**
     * deletes the given sidebar-type component from the array
     *
     * @param sidebarType the sidebar-type component to be deleted
     */
    public deleteCounter(sidebarType: SidebarTypeComponent) {
        this.sideBarType = this.sideBarType.filter( type => type !== sidebarType);
    }


    public ReloadSideBarData() {
        this.reloadData.next(true);
    }
}