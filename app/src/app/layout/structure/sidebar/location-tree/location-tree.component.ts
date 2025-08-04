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

import { Component, OnInit, OnDestroy } from '@angular/core';
import { NestedTreeControl } from '@angular/cdk/tree';
import { MatTreeNestedDataSource } from '@angular/material/tree';
import { Router } from '@angular/router';

import { ReplaySubject, BehaviorSubject, Subscription } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

import { LocationService } from 'src/app/framework/services/location.service';
import { TreeManagerService } from 'src/app/services/tree-manager.service';
import { ObjectService } from 'src/app/framework/services/object.service';

import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { RenderResult } from '../../../../framework/models/cmdb-render';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';

/* -------------------------------------------------------------------------- */
/*                                 INTERFACES                                 */
/* -------------------------------------------------------------------------- */

interface LocationNode {
    name: string;
    icon: string;
    parent: number;
    object_id: number;
    children?: LocationNode[];
}

/* -------------------------------------------------------------------------- */

@Component({
    selector: 'location-tree',
    templateUrl: './location-tree.component.html',
    styleUrls: ['./location-tree.component.scss'],
})
export class LocationTreeComponent implements OnInit, OnDestroy {

    private unsubscribe: ReplaySubject<void> = new ReplaySubject<void>();
    public changedReference: BehaviorSubject<any> = new BehaviorSubject<any>(undefined);

    objectServiceSubscription: Subscription;
    locationServiceSubscription: Subscription;

    treeControl = new NestedTreeControl<LocationNode>(node => node.children);
    dataSource = new MatTreeNestedDataSource<LocationNode>();


    /**
     * used for highlighting the selected location
     */
    public selectedLocationID: number;
    public searchString: string = '';

    /* -------------------------------------------------------------------------- */
    /*                                LIFE - CYCLE                                */
    /* -------------------------------------------------------------------------- */


    constructor(private locationService: LocationService,
        private treeManagerService: TreeManagerService,
        private objectService: ObjectService,
        private route: Router) {

    }


    public ngOnInit() {
        this.objectServiceSubscription = this.objectService.objectActionSource.subscribe(
            (action: string) => this.onObjectActionEventRecieved(action)
        );

        this.locationServiceSubscription = this.locationService.locationActionSource.subscribe(
            (action: string) => this.onLocationActionEventRecieved(action)
        );

        this.getLocationTree();
    }

    public ngOnDestroy(): void {
        this.objectServiceSubscription?.unsubscribe();
    }


    /**
    * Reset the search string
    */
    handleSearchReset() {
        this.searchString = "";
    }


    /**
    * Filter function for leaf nodes
    */
    filterLeafNode(node: LocationNode): boolean {

        if (!this.searchString || !node.name) {
            return false;
        }
        const nodeName = node.name.toLowerCase();
        return nodeName.indexOf(this.searchString.toLowerCase()) === -1;
    }


    /**
     * Filters a parent node based on a search string.
     * 
     * @param node The parent node to be filtered.
     * @returns A boolean indicating whether the node should be filtered out or not.
     */
    filterParentNode(node: LocationNode): boolean {
        if (!this.searchString) {
            return false;
        }

        // Check if the search string matches the parent node
        if (node.name.toLowerCase().indexOf(this.searchString?.toLowerCase()) !== -1) {
            return false;
        }

        // Check if any descendants match the search string
        const descendants = this.treeControl.getDescendants(node);
        if (descendants.some((descendantNode) => descendantNode.name.toLowerCase().indexOf(this.searchString?.toLowerCase()) !== -1)) {
            return false;
        }

        // If the search string matches the immediate child, show the parent
        const immediateChild = descendants.find((descendantNode) => descendantNode.name === node.name + 1);
        if (immediateChild && immediateChild.name.toLowerCase().indexOf(this.searchString?.toLowerCase()) !== -1) {
            return true;
        }

        return true;
    }


    /* -------------------------------------------------------------------------- */
    /*                               TREE FUNCTIONS                               */
    /* -------------------------------------------------------------------------- */


    /**
    * Get all locations except the root location formatted as hierarchical tree data
    */
    private getLocationTree() {
        const params: CollectionParameters = {
            filter: [{ $match: { public_id: { $gt: 1 } } }],
            limit: 0, sort: 'public_id', order: 1, page: 1
        };

        this.locationService.getLocationsTree(params).pipe(takeUntil(this.unsubscribe))
            .subscribe((apiResponse: APIGetMultiResponse<RenderResult>) => {
                this.dataSource.data = this.forceCast<LocationNode[]>(apiResponse.results);
                this.treeManagerService.expandNodes(this.dataSource.data, this.treeControl);
            });
    }


    /**
     * EventListener function which will update the tree when objects were changed
     * 
     * @param action (string): Type of object action (create, delete or update)
     */
    public onObjectActionEventRecieved(action: string) {
        this.getLocationTree();
    }

    /**
  * EventListener function which will update the tree when objects were changed
  * 
  * @param action (string): Type of object action (create, delete or update)
  */
    public onLocationActionEventRecieved(action: string) {
        this.getLocationTree();
    }

    /**
    * Set the selected location and loads the object overview in the content view
    * 
    * @param clickedObjectID the objectID of the location which is clicked in location tree
    */
    public onLocationElementClicked(clickedObjectID: number) {
        this.selectedLocationID = clickedObjectID;
        this.route.navigateByUrl('/framework/object/view/' + clickedObjectID);
    }


    /**
     * Updates status of all expanded locations and saves them
     */
    public onExpandClicked() {
        this.treeManagerService.extractExpandedIds(this.treeControl.expansionModel.selected);
    }

    /**
    * Checks if a node has a child
    */
    hasChild = (_: number, node: LocationNode) => !!node.children && node.children.length > 0;

    /**
     * Reloads the tree after an update
     */
    public reloadTree() {
        this.ngOnInit();
    }

    /* -------------------------------------------------------------------------- */
    /*                             HELPER - FUNCTIONS                             */
    /* -------------------------------------------------------------------------- */


    /**
    * This function is used to force cast to LocationNode[]
    * 
    * @param input api response with location tree
    * @returns array of LocationNode
    */
    public forceCast<T>(input: any): T {
        return input;
    }
}