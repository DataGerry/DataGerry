import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  CiExplorerScope,
  DEFAULT_CI_EXPLORER_SCOPE,
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

  /** The optional edge sources, spelled the way the REST route names them. */
  private buildScope(scope: CiExplorerScope): string {
    return `&with_locations=${scope.withLocations}` +
           `&with_ipam_relations=${scope.withIpamRelations}` +
           `&with_port_connections=${scope.withPortConnections}`;
  }

  /* ---------------- initial root + 1-hop ------------------------- */
  loadWithRoot(
    targetId: number,
    types: number[] = [],
    relations: number[] = [],
    scope: CiExplorerScope = DEFAULT_CI_EXPLORER_SCOPE
  ): Observable<GraphRespWithRoot> {
    const url =
      `${this.servicePrefix}?target_id=${targetId}` +
      `&target_type=BOTH&with_root=true&item_limit=${CI_EXPLORER_ITEM_LIMIT}` +
      this.buildScope(scope) +
      this.buildFilters(types, relations);

    return this.handleGetRequest<GraphRespWithRoot>(url);
  }

  /* ---------------- expand children ------------------------------ */
  expandChild(
    targetId: number,
    types: number[] = [],
    relations: number[] = [],
    scope: CiExplorerScope = DEFAULT_CI_EXPLORER_SCOPE
  ): Observable<GraphRespChildren> {
    const url =
      `${this.servicePrefix}?target_id=${targetId}` +
      `&target_type=CHILD&with_root=false&item_limit=${CI_EXPLORER_ITEM_LIMIT}` +
      this.buildScope(scope) +
      this.buildFilters(types, relations);

    return this.handleGetRequest<GraphRespChildren>(url);
  }

  /* ---------------- expand parents ------------------------------- */
  expandParent(
    targetId: number,
    types: number[] = [],
    relations: number[] = [],
    scope: CiExplorerScope = DEFAULT_CI_EXPLORER_SCOPE
  ): Observable<GraphRespParents> {
    const url =
      `${this.servicePrefix}?target_id=${targetId}` +
      `&target_type=PARENT&with_root=false&item_limit=${CI_EXPLORER_ITEM_LIMIT}` +
      this.buildScope(scope) +
      this.buildFilters(types, relations);

    return this.handleGetRequest<GraphRespParents>(url);
  }
}
