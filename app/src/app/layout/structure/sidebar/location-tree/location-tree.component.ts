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

import { Component, OnInit, OnDestroy, ChangeDetectorRef } from '@angular/core';
import { FlatTreeControl } from '@angular/cdk/tree';
import { MatTreeFlatDataSource, MatTreeFlattener } from '@angular/material/tree';
import { Router } from '@angular/router';


import { ReplaySubject, BehaviorSubject, Subscription } from 'rxjs';
import { takeUntil } from 'rxjs/operators';


import { ObjectRelationService } from 'src/app/framework/services/object-relation.service';
import { TreeManagerService } from 'src/app/services/tree-manager.service';
import { ObjectService } from 'src/app/framework/services/object.service';


import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { RenderResult } from '../../../../framework/models/cmdb-render';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';


/* -------------------------------------------------------------------------- */
/*                                 INTERFACES                                 */
/* -------------------------------------------------------------------------- */


interface ObjectRelationNode {
 relation_id: number;
 relation_parent_id: number;
 relation_child_id: number;
 field_values: Array<{ name: string; value: any }>;
 relation_parent_type_id?: number;
 relation_child_type_id?: number;
}


interface LocationTreeNode {
 name: string;
 icon: string;
 object_id: number;
 parent_id: number;
 children: LocationTreeNode[];
 relation_id: number;
 isLoading: boolean;
 hasBeenExpanded: boolean;
 isDuplicate?: boolean;
 rootId?: number;
}


/** Flat node with expandable and level information */
interface LocationTreeFlatNode {
 name: string;
 icon: string;
 object_id: number;
 parent_id: number;
 relation_id: number;
 isLoading: boolean;
 hasBeenExpanded: boolean;
 level: number;
 expandable: boolean;
 isDuplicate?: boolean;
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
   // Track object IDs per root hierarchy to detect duplicates
   private rootObjectIds = new Map<number, Set<number>>();



   objectServiceSubscription: Subscription;


   // Tree control for flat tree structure
   treeControl: FlatTreeControl<LocationTreeFlatNode>;


   // Tree flattener to convert nested nodes to flat nodes
   private treeFlattener: MatTreeFlattener<LocationTreeNode, LocationTreeFlatNode>;


   // Data source for flat tree
   dataSource: MatTreeFlatDataSource<LocationTreeNode, LocationTreeFlatNode>;


   /**
    * used for highlighting the selected location
    */
   public selectedLocationID: number;
   public searchString: string = '';


   /* -------------------------------------------------------------------------- */
   /*                                LIFE - CYCLE                                */
   /* -------------------------------------------------------------------------- */


   constructor(private objectRelationService: ObjectRelationService,
       private treeManagerService: TreeManagerService,
       private objectService: ObjectService,
       private route: Router,
       private changesRef: ChangeDetectorRef) {


       // Initialize the tree flattener
       this.treeFlattener = new MatTreeFlattener(
           this.transformer,
           node => node.level,
           node => node.expandable,
           node => node.children
       );


       // Initialize the tree control
       this.treeControl = new FlatTreeControl<LocationTreeFlatNode>(
           node => node.level,
           node => node.expandable
       );


       // Initialize the data source
       this.dataSource = new MatTreeFlatDataSource(this.treeControl, this.treeFlattener);
   }


   /**
    * Transformer to convert nested node to flat node
    */
   private transformer = (node: LocationTreeNode, level: number): LocationTreeFlatNode => {
       return {
           name: node.name,
           icon: node.icon,
           object_id: node.object_id,
           parent_id: node.parent_id,
           relation_id: node.relation_id,
           isLoading: node.isLoading,
           hasBeenExpanded: node.hasBeenExpanded,
           level: level,
           expandable: !node.hasBeenExpanded || (node.children && node.children.length > 0),
           isDuplicate: node.isDuplicate
       };
   };


   public ngOnInit() {
       this.objectServiceSubscription = this.objectService.objectActionSource.subscribe(
           (action: string) => this.onObjectActionEventRecieved(action)
       );


       this.loadRootNodes();
   }


   public ngOnDestroy(): void {
       this.objectServiceSubscription?.unsubscribe();
       this.unsubscribe.next();
       this.unsubscribe.complete();
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
   filterLeafNode(node: LocationTreeFlatNode): boolean {
       if (!this.searchString || !node.name) {
           return false;
       }
       const nodeName = node.name.toLowerCase();
       return nodeName.indexOf(this.searchString.toLowerCase()) === -1;
   }


   /**
    * Filters a parent node based on a search string.
    */
   filterParentNode(node: LocationTreeFlatNode): boolean {
       if (!this.searchString) {
           return false;
       }


       // Check if the search string matches the parent node
       if (node.name.toLowerCase().indexOf(this.searchString?.toLowerCase()) !== -1) {
           return false;
       }


       // For flat tree, we need to check descendants differently
       // This is a simplified version - may need enhancement for complex filtering
       return true;
   }


   /* -------------------------------------------------------------------------- */
   /*                               TREE FUNCTIONS                               */
   /* -------------------------------------------------------------------------- */


   /**
    * Load root nodes using the "is_root" filter
    */
   private loadRootNodes() {
       const params: CollectionParameters = {
           filter: [{ $match: { "field_values": { "$elemMatch": { "value": "is_root" } } } }],
           limit: 0, sort: 'public_id', order: 1, page: 1
       };


       this.objectRelationService.getObjectRelations(params).pipe(takeUntil(this.unsubscribe))
           .subscribe((apiResponse: APIGetMultiResponse<ObjectRelationNode>) => {
              
               if (apiResponse.results && apiResponse.results.length > 0) {
                   this.loadObjectSummaries(apiResponse.results, true).then(rootNodes => {
                      
                       // Set the data source with the root nodes
                       this.dataSource.data = rootNodes;
                      
                       // Force change detection
                       this.changesRef.detectChanges();
                   });
               } else {
                   this.dataSource.data = [];
                   this.changesRef.detectChanges();
               }
           });
   }


   /**
    * Load children for a specific parent node
    */
   private async loadChildren(parentNode: LocationTreeNode): Promise<void> {
       if (parentNode.isLoading || parentNode.hasBeenExpanded) {
           return;
       }


       parentNode.isLoading = true;
       this.changesRef.detectChanges();


       try {
           const params: CollectionParameters = {
               filter: [{ $match: { relation_parent_id: parentNode.object_id } }],
               limit: 0, sort: 'public_id', order: 1, page: 1
           };




           const response = await this.objectRelationService.getObjectRelations(params).toPromise();
           const results = response?.results || [];




           if (results.length > 0) {
               const childNodes = await this.loadObjectSummaries(results, false, parentNode);


               // Check for duplicates within the root hierarchy
               const rootId = this.findRootId(parentNode);
               this.checkForDuplicates(rootId, childNodes);


               // Update the parent node with children
               parentNode.children = childNodes;
               parentNode.hasBeenExpanded = true;
               parentNode.isLoading = false;




               // Refresh the data source to reflect changes
               this.refreshDataSource();


               // Expand the parent node to show children
            //    const flatNode = this.findFlatNode(parentNode.object_id);
            //    if (flatNode && !this.treeControl.isExpanded(flatNode)) {
            //        this.treeControl.expand(flatNode);
            //    }


           } else {
               parentNode.children = [];
               parentNode.hasBeenExpanded = true;
               parentNode.isLoading = false;


               this.refreshDataSource();
           }


       } catch (error) {
           parentNode.isLoading = false;
           parentNode.children = [];
           this.changesRef.detectChanges();
       }
   }


   /**
    * Find a flat node by object_id
    */
   private findFlatNode(objectId: number): LocationTreeFlatNode | null {
       const flatNodes = this.treeControl.dataNodes;
       return flatNodes.find(node => node.object_id === objectId) || null;
   }


   /**
    * Refresh the data source to ensure change detection
    */
//    private refreshDataSource(): void {
//        // Save currently expanded nodes before updating
//        const expandedObjectIds = this.treeControl.expansionModel.selected
//            .map(node => node.object_id);
       
//        console.log('Currently expanded nodes before refresh:', expandedObjectIds);
       
//        // Create a new reference to trigger change detection
//        this.dataSource.data = [...this.dataSource.data];
       
//        console.log('Data source refreshed, expanded nodes after:', this.treeControl.expansionModel.selected.length);
       
//        // Restore expansion state after a brief delay
//        setTimeout(() => {
//            console.log('Restoring expansion state for:', expandedObjectIds);
//            expandedObjectIds.forEach(objectId => {
//                const node = this.findFlatNode(objectId);
//                if (node && !this.treeControl.isExpanded(node)) {
//                    console.log('Re-expanding node:', objectId);
//                    this.treeControl.expand(node);
//                }
//            });
//        });
       
//        this.changesRef.markForCheck();
//        this.changesRef.detectChanges();
//    }

private refreshDataSource(): void {
    // snapshot exactly what's open right now
    const expandedIds = new Set(
      this.treeControl.dataNodes
        .filter(n => this.treeControl.isExpanded(n))
        .map(n => n.object_id)
    );
  
    // trigger CD without changing object identities of nodes
    this.dataSource.data = [...this.dataSource.data];
  
    // restore expansion state on the new flat list only for those that were open
    queueMicrotask(() => {
      this.treeControl.dataNodes.forEach(n => {
        if (expandedIds.has(n.object_id)) this.treeControl.expand(n);
        else this.treeControl.collapse(n);
      });
      this.changesRef.markForCheck();
      this.changesRef.detectChanges();
    });
  }
  


   /**
    * Load object summaries for relation nodes using batch fetching
    */
   private async loadObjectSummaries(relations: ObjectRelationNode[], useParentId: boolean = false, parentNode?: LocationTreeNode): Promise<LocationTreeNode[]> {
       const objectIds = relations.map(relation => useParentId ? relation.relation_parent_id : relation.relation_child_id);
       const uniqueIds = Array.from(new Set(objectIds));


       if (uniqueIds.length === 0) {
           return [];
       }




       try {
           const params: CollectionParameters = {
               filter: [{ $match: { "public_id": { "$in": uniqueIds } } }],
               limit: 0, sort: 'public_id', order: 1, page: 1
           };


           const apiResponse = await this.objectService.getObjects(params).toPromise();
           const objectMap = new Map<number, RenderResult>();
          


           (apiResponse?.results || []).forEach((obj: RenderResult) => {
               if (obj?.object_information?.object_id) {
                   objectMap.set(obj.object_information.object_id, obj);
               }
           });


           const nodes = relations.map(relation => {
               const targetObjectId = useParentId ? relation.relation_parent_id : relation.relation_child_id;
               const object = objectMap.get(targetObjectId);
              
               if (object) {
                   const typeLabel = object.type_information?.type_label + ' - ';
                   const objectId = object.object_information?.object_id || targetObjectId;
                   const summaryLine = object.summary_line || '';
                  
                   const name = `#${objectId} ${typeLabel} ${summaryLine}`.trim();
                   
                   // Determine rootId: for root nodes, it's their own ID; for children, it's the parent's rootId
                   const rootId = useParentId ? targetObjectId : (parentNode?.rootId || parentNode?.object_id || targetObjectId);
                  
                   const node: LocationTreeNode = {
                       name: name,
                       icon: object.type_information?.icon,
                       object_id: targetObjectId,
                       parent_id: relation.relation_parent_id,
                       relation_id: relation.relation_id,
                       children: [],
                       isLoading: false,
                       hasBeenExpanded: false,
                       rootId: rootId
                   };
                  
                   return node;
               }
               return null;
           }).filter((node): node is LocationTreeNode => !!node);


           return nodes;
          
       } catch (error) {
        //    return this.createFallbackNodes(relations, useParentId);
       }
   }



   /**
    * Extract name from field values (fallback method)
    */
   private extractNameFromFieldValues(fieldValues: Array<{ name: string; value: any }>): string {
       const nameField = fieldValues.find(field => field.name === 'name');
       return nameField ? String(nameField.value) : '';
   }


   /**
    * EventListener function which will update the tree when objects were changed
    */
   public onObjectActionEventRecieved(action: string) {
       this.loadRootNodes();
   }


   /**
   * Set the selected location and loads the object overview in the content view
   */
   public onLocationElementClicked(clickedObjectID: number) {
       this.selectedLocationID = clickedObjectID;
       this.route.navigateByUrl('/framework/object/view/' + clickedObjectID);
   }


   /**
   * Checks if a node has children (for the flat tree control)
   */
   hasChild = (_: number, node: LocationTreeFlatNode) => {
       return node.expandable;
   };


   /**
    * Handle node expansion
    */
//    public async onExpandClicked(node: LocationTreeFlatNode): Promise<void> {
//        console.log('Expand clicked for node:', node.object_id);
      
//        // Find the corresponding nested node
//        const nestedNode = this.findNestedNode(node.object_id);
//        if (!nestedNode) {
//            console.error('Nested node not found for object_id:', node.object_id);
//            return;
//        }


//        if (!nestedNode.hasBeenExpanded && !nestedNode.isLoading) {
//            console.log('Loading children...');
//            await this.loadChildren(nestedNode);
//        }
      
//        // Update tree manager
//        this.treeManagerService.extractExpandedIds(this.treeControl.expansionModel.selected);
//    }

public async onExpandClicked(node: LocationTreeFlatNode, ev?: MouseEvent): Promise<void> {
    ev?.stopPropagation(); // make sure it's only our handler
    const isOpen = this.treeControl.isExpanded(node);
  
    if (isOpen) {
      this.treeControl.collapse(node);
      this.treeManagerService.extractExpandedIds(this.treeControl.expansionModel.selected);
      return;
    }
  
    // Optimistic expand FIRST so refreshDataSource snapshots it as expanded
    this.treeControl.expand(node);
  
    const nestedNode = this.findNestedNode(node.object_id);
    if (!nestedNode) return;
  
    if (!nestedNode.hasBeenExpanded && !nestedNode.isLoading) {
      await this.loadChildren(nestedNode);
    }
  
    this.treeManagerService.extractExpandedIds(this.treeControl.expansionModel.selected);
  }
  
  


   /**
    * Find a nested node by object_id
    */
   private findNestedNode(objectId: number): LocationTreeNode | null {
       const findNode = (nodes: LocationTreeNode[]): LocationTreeNode | null => {
           for (const node of nodes) {
               if (node.object_id === objectId) {
                   return node;
               }
               if (node.children) {
                   const found = findNode(node.children);
                   if (found) return found;
               }
           }
           return null;
       };
      
       return findNode(this.dataSource.data);
   }


   /**
    * Reloads the tree after an update
    */
   public reloadTree() {
       this.loadRootNodes();
   }


   /**
    * Find the root ID for a given node using the stored rootId
    */
   private findRootId(node: LocationTreeNode): number {
       // Use the stored rootId if available, otherwise fallback to object_id
       return node.rootId || node.object_id;
   }

   /**
    * Check for duplicate object IDs within the same root hierarchy
    */
   private checkForDuplicates(rootId: number, childNodes: LocationTreeNode[]): void {
       // Initialize the set for this root if it doesn't exist
       if (!this.rootObjectIds.has(rootId)) {
           this.rootObjectIds.set(rootId, new Set<number>());
       }
       
       const rootSet = this.rootObjectIds.get(rootId)!;
       
       console.log('Checking duplicates for root:', rootId, 'existing IDs:', Array.from(rootSet));
       
       childNodes.forEach(node => {
           if (rootSet.has(node.object_id)) {
               // Mark as duplicate
               node.isDuplicate = true;
               console.log('DUPLICATE DETECTED: Object ID', node.object_id, 'in root', rootId);
           } else {
               // Add to the set
               rootSet.add(node.object_id);
               node.isDuplicate = false;
               console.log('New object added:', node.object_id, 'to root', rootId);
           }
       });
       
       console.log('Root set after processing:', Array.from(rootSet));
   }

   /**
    * Create fallback nodes when API calls fail
    */
   private createFallbackNodes(relations: ObjectRelationNode[], useParentId: boolean): LocationTreeNode[] {
       return relations.map(relation => {
           const targetObjectId = useParentId ? relation.relation_parent_id : relation.relation_child_id;
           const fallbackName = useParentId ? 
               `#${relation.relation_parent_id} Unnamed Location` : 
               this.extractNameFromFieldValues(relation.field_values);
          
           return {
               name: fallbackName,
               icon: 'fas fa-folder',
               object_id: targetObjectId,
               parent_id: relation.relation_parent_id,
               relation_id: relation.relation_id,
               children: [],
               isLoading: false,
               hasBeenExpanded: false
           };
       });
   }

   /**
    * TrackBy to stabilize DOM rendering for mat-tree
    */
   public trackById(_index: number, node: LocationTreeFlatNode): number {
       return node.object_id;
   }
}
