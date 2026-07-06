import { CmdbRelation } from "./relation.model";

// Interface for ExtendedRelation used in relation selection modal
export interface ExtendedRelation extends CmdbRelation {
  canBeParent: boolean;
  canBeChild: boolean;
}
