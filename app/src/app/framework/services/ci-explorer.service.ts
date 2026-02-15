

import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  GraphRespWithRoot,
  GraphRespChildren,
  GraphRespParents,
} from '../models/ci-explorer.model';
import { BaseApiService } from 'src/app/core/services/base-api.service';

export const CI_EXPLORER_ITEM_LIMIT = 20;
@Injectable({ providedIn: 'root' })
export class CiExplorerService extends BaseApiService<never> {
  public servicePrefix = 'ci_explorer/items';

  /* --------------------------------------------------------------- */
  /* helpers                                                         */
  /* --------------------------------------------------------------- */
  private buildFilters(types: number[], relations: number[]): string {
    let qs = '';
    if (types?.length)      { qs += `&types_filter=[${types.join(',')}]`; }
    if (relations?.length)  { qs += `&relations_filter=[${relations.join(',')}]`; }
    return qs;
  }

  /* ---------------- initial root + 1-hop ------------------------- */
  loadWithRoot(
    targetId: number,
    types: number[] = [],
    relations: number[] = [],
    withLocations: boolean = true
  ): Observable<GraphRespWithRoot> {
    const url =
      `${this.servicePrefix}?target_id=${targetId}` +
      `&target_type=BOTH&with_root=true&with_locations=${withLocations}&item_limit=${CI_EXPLORER_ITEM_LIMIT}` +
      this.buildFilters(types, relations);

    return this.handleGetRequest<GraphRespWithRoot>(url);
  }

  /* ---------------- expand children ------------------------------ */
  expandChild(
    targetId: number,
    types: number[] = [],
    relations: number[] = [],
    withLocations: boolean = true
  ): Observable<GraphRespChildren> {
    const url =
      `${this.servicePrefix}?target_id=${targetId}` +
      `&target_type=CHILD&with_root=false&with_locations=${withLocations}&item_limit=${CI_EXPLORER_ITEM_LIMIT}` +
      this.buildFilters(types, relations);

    return this.handleGetRequest<GraphRespChildren>(url);
  }

  /* ---------------- expand parents ------------------------------- */
  expandParent(
    targetId: number,
    types: number[] = [],
    relations: number[] = [],
    withLocations: boolean = true
  ): Observable<GraphRespParents> {
    const url =
      `${this.servicePrefix}?target_id=${targetId}` +
      `&target_type=PARENT&with_root=false&with_locations=${withLocations}&item_limit=${CI_EXPLORER_ITEM_LIMIT}` +
      this.buildFilters(types, relations);

    return this.handleGetRequest<GraphRespParents>(url);
  }
}
