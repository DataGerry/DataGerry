import { CmdbRelation } from "./relation.model";

// Interface for ExtendedRelation used in relation selection modal
export interface ExtendedRelation extends CmdbRelation {
  canBeParent: boolean;
  canBeChild: boolean;
}
<<<<<<< HEAD

// Interface for raw relation instances from the API
export interface ObjectRelationInstance {
  public_id: number;
  relation_id: number;
  relation_parent_id: number;
  relation_child_id: number;
  field_values: Array<{ name: string; value: any }>;
  definition?: CmdbRelation;
}

// Extended interface for table data
export interface ExtendedObjectRelationInstance extends ObjectRelationInstance {
  counterpart_id: number;
  type: string;
}

// Interface for grouped relation instances under each tab
export interface RelationGroup {
  relationId: number;
  isParent: boolean;
  tabLabel: string;
  tabColor: string;
  tabIcon: string;
  instances: ExtendedObjectRelationInstance[];
  selectedInstances?: ExtendedObjectRelationInstance[];
  selectedInstanceIDs?: number[];
  total: number;    // total number of items for this group
  page?: number;     // current page for this group
  pageSize?: number; // items per page for this group
  definition: CmdbRelation;
}
=======
>>>>>>> origin/version-3.2
