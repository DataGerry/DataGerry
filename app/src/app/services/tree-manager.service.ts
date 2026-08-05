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

import {NestedTreeControl} from '@angular/cdk/tree';

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


export class TreeManagerService {
    /**
     * Tracks all expanded locations by their object_id
     */
    expandedIds: number[] = [];


    /* -------------------------------------------------------------------------- */
    /*                               TREE FUNCTIONS                               */
    /* -------------------------------------------------------------------------- */


    /**
     * Extracts all object_ids of expandedNodes which are expanded 
     * 
     * @param expandedNodes (LocationsNode[]): Expanded nodes from tree control
     */
    public extractExpandedIds(expandedNodes: LocationNode[]){
      let expandedIds: number[] = [];

      for(let node of expandedNodes){
        expandedIds.push(node.object_id);
      }

      this.expandedIds = expandedIds;
    }

    /**
     * Expands all previously expanded nodes
     * 
     * @param treeData (LocationNode[]): The current tree data nodes 
     * @param treeControl (NestedTreeControl<LocationNode>): Control of the tree
     */
    public expandNodes(treeData: LocationNode[], treeControl:  NestedTreeControl<LocationNode>){

      for (var node of treeData){
        for(var expandedID of this.expandedIds){
          if(expandedID == node.object_id && node.children){
            treeControl.expand(node);
            continue;
          }

          //check also the children
          if(node.children){
            this.expandNodes(node.children, treeControl);
          }
        }
      }
    }
}