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
import { Injectable, inject } from '@angular/core';

import {
    BehaviorSubject, Observable, Subscription, catchError, firstValueFrom, map, of, shareReplay, skip, switchMap, tap
} from 'rxjs';

import { UserService } from 'src/app/management/services/user.service';
import { ObjectService } from '../../framework/services/object.service';
import { LocationService, LocationTreeNode } from '../../framework/services/location.service';
import { IpamTreeService } from '../structure/sidebar/ipam-tree/services/ipam-tree.service';

import { User } from 'src/app/management/models/user';
import { CmdbCategoryTree } from '../../framework/models/cmdb-category';
import { CategoryService } from '../../framework/services/category.service';
import { SidebarTypeComponent } from '../structure/sidebar/sidebar-type.component';
import { IpamTreeResponse } from '../structure/sidebar/ipam-tree/models/ipam-tree.types';

const LOCATION_ROOTS_CACHE_KEY = 'location-roots';
const IPAM_TREE_CACHE_KEY = 'ipam-tree';
const objectCountCacheKey = (typeId: number) => `object-count:${typeId}`;
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

    /**
     * Tracks which category nodes are expanded (keyed by category public_id).
     */
    private readonly expandedCategories = new Set<number>();

    /** Sidebar sections are re-created on collapse, expand, hover and tab switch; they read through this. */
    private readonly responseCache = new Map<string, Observable<unknown>>();

    private readonly locationService = inject(LocationService);
    private readonly ipamTreeService = inject(IpamTreeService);

    /* -------------------------------------------------- GETTER/SETTER ------------------------------------------------- */

    /**
     * Get the subject of the current category tree.
     */
    public get categoryTree(): BehaviorSubject<CmdbCategoryTree> {
        return this.categoryTreeObserver;
    }


    /**
     * Emits whenever the sidebar was asked to refresh what it shows, so every section can reload
     * itself off one signal instead of each one listening to the services it happens to read from.
     *
     * The current value is skipped: a section subscribes right after it has loaded, and would
     * otherwise reload immediately.
     */
    public get reloaded(): Observable<boolean> {
        return this.reloadData.asObservable().pipe(skip(1));
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

        this.objectService.objectActionSource.subscribe(() => {
            this.responseCache.delete(LOCATION_ROOTS_CACHE_KEY);
            this.responseCache.delete(IPAM_TREE_CACHE_KEY);
        });

        this.locationService.locationActionSource.subscribe(() => this.responseCache.delete(LOCATION_ROOTS_CACHE_KEY));
    }

    /* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

    /**
     * Whether the given category is currently expanded in the sidebar tree.
     *
     * @param categoryId the category public_id
     */
    public isCategoryExpanded(categoryId: number): boolean {
        return this.expandedCategories.has(categoryId);
    }


    /**
     * Persists the expanded/collapsed state of a category so it survives the
     * sidebar being collapsed to its rail and expanded again.
     *
     * @param categoryId the category public_id
     * @param expanded whether the category is expanded
     */
    public setCategoryExpanded(categoryId: number, expanded: boolean): void {
        if (expanded) {
            this.expandedCategories.add(categoryId);
        } else {
            this.expandedCategories.delete(categoryId);
        }
    }


    /**
     * Load Category Tree {@link CmdbCategoryTree}.
     */
    public loadCategoryTree() {
        this.categoryService.getCategoryTree().subscribe((tree: CmdbCategoryTree) => {
            this.categoryTreeObserver.next(tree);
        });
    }


    /**
     * gets the object count of the given type
     *
     * @param typeID: the type id of the type of which the objects are counted
     */
    private getObjectCount(typeID: number): Observable<number> {
        return this.cached(objectCountCacheKey(typeID), () => this.objectService.countObjectsByType(typeID)).pipe(
            catchError(() => of(0))
        );
    }


    /**
     * Top level of the location tree, shared by the expanded panel and the collapsed-rail flyout.
     */
    public getLocationRoots(): Observable<LocationTreeNode[]> {
        return this.cached(LOCATION_ROOTS_CACHE_KEY, () => this.locationService.getTreeRoots());
    }


    /**
     * Top level of the IPAM tree, shared by the expanded panel and the collapsed-rail flyout.
     */
    public getIpamTree(): Observable<IpamTreeResponse> {
        // A copy per read: the tree writes lazily loaded children onto these nodes.
        return this.cached(IPAM_TREE_CACHE_KEY, () => this.ipamTreeService.getTree()).pipe(
            map(tree => structuredClone(tree))
        );
    }


    /** Drops every cached sidebar response, so the next session starts from fresh data. */
    public clearCache(): void {
        this.responseCache.clear();
    }


    /**
     * updates the objectCounter of the affected sidebar-type component
     *
     * @param typeID the type id with to the sidebar-typ component will be filtered
     */
    public async updateTypeCounter(typeID: number): Promise<void> {
        this.responseCache.delete(objectCountCacheKey(typeID));

        const sidebarTypes = this.sideBarType.filter(type => type.type.public_id === typeID);

        if (sidebarTypes.length) {
            sidebarTypes.forEach(sidebarType => sidebarType.objectCounter = null);

            const count = await firstValueFrom(this.getObjectCount(typeID));
            sidebarTypes.forEach(sidebarType => {
                if (this.sideBarType.includes(sidebarType)) {
                    sidebarType.objectCounter = count;
                }
            });
        }
    }


    /**
     * inserts the sidebar-type component into an array and updates its counter
     *
     * @param sidebarType the sidebar-type component which will be inserted
     */
    public initializeCounter(sidebarType: SidebarTypeComponent): Subscription {
        if (!this.sideBarType.includes(sidebarType)) {
            this.sideBarType.push(sidebarType);
        }

        return this.reloadData.pipe(
            tap(() => sidebarType.objectCounter = null),
            switchMap(() => this.getObjectCount(sidebarType.type.public_id))
        ).subscribe((count: number) => sidebarType.objectCounter = count);
    }


    /**
     * deletes the given sidebar-type component from the array
     *
     * @param sidebarType the sidebar-type component to be deleted
     */
    public deleteCounter(sidebarType: SidebarTypeComponent) {
        this.sideBarType = this.sideBarType.filter(type => type !== sidebarType);
    }


    /** Announces that the sidebar's data is stale. Every section listening on `reloaded` reloads. */
    public ReloadSideBarData() {
        this.responseCache.clear();
        this.reloadData.next(true);
    }


    /**
     * Shares one response per key until it is invalidated. A failed request is not kept, so the
     * next read retries it.
     */
    private cached<T>(key: string, request: () => Observable<T>): Observable<T> {
        let response$ = this.responseCache.get(key) as Observable<T> | undefined;

        if (!response$) {
            response$ = request().pipe(shareReplay({ bufferSize: 1, refCount: false }));
            this.responseCache.set(key, response$);
        }

        return response$;
    }
}
