import { Injectable } from '@angular/core';
import { HttpHeaders, HttpParams, HttpResponse } from '@angular/common/http';
import { Observable, map } from 'rxjs';
import { ApiCallService, ApiServicePrefix, resp } from '../../services/api-call.service';
import {
  APIGetMultiResponse,
  APIGetSingleResponse,
  APIInsertSingleResponse,
  APIUpdateSingleResponse,
  APIDeleteSingleResponse
} from '../../services/models/api-response';
import { CollectionParameters } from '../../services/models/api-parameter';
import {
  ObjectRelationInstancesQuery,
  ObjectRelationInstancesResponse,
  ObjectRelationTab
} from '../models/object-relation.model';

export interface CmdbObjectRelationCreateDto {
  relation_id: number;
  relation_parent_id: number;
  relation_child_id: number;
  author_id: number;
  field_values: Array<{ name: string; value: any }>;
  relation_parent_type_id?: number;
  relation_child_type_id?: number;
}

@Injectable({
  providedIn: 'root'
})
export class ObjectRelationService implements ApiServicePrefix {
  public servicePrefix: string = 'object_relations';
  private options = {
    headers: new HttpHeaders({ 'Content-Type': 'application/json' }),
    params: {},
    observe: resp
  };

  constructor(private api: ApiCallService) { }

  // Get list of object relations
  public getObjectRelations(
    params: CollectionParameters = {
      filter: undefined,
      limit: 10,
      sort: 'public_id',
      order: 1,
      page: 1
    }
  ): Observable<APIGetMultiResponse<any>> {
    const options = { ...this.options };
    let httpParams = new HttpParams();

    if (params.filter) {
      httpParams = httpParams.set('filter', JSON.stringify(params.filter));
    }
    if (params.projection) {
      httpParams = httpParams.set('projection', JSON.stringify(params.projection));
    }
    httpParams = httpParams
      .set('limit', params.limit.toString())
      .set('sort', params.sort)
      .set('order', params.order.toString())
      .set('page', params.page.toString());

    options.params = httpParams;
    return this.api.callGet<any>(this.servicePrefix + '/', options).pipe(
      map((apiResponse: HttpResponse<APIGetMultiResponse<any>>) => apiResponse.body)
    );
  }

  /**
   * Loads the relation tabs for an object.
   */
  public getRelationTabs(objectID: number): Observable<ObjectRelationTab[]> {
    const options = { ...this.options, params: new HttpParams() };
    return this.api.callGet<any>(`${this.servicePrefix}/tabs/${objectID}`, options).pipe(
      map((apiResponse: HttpResponse<{ results: ObjectRelationTab[] }>) => apiResponse.body?.results ?? [])
    );
  }


  /**
   * Loads a single, paginated relation tab. 
   */
  public getRelationTabInstances(
    objectID: number,
    query: ObjectRelationInstancesQuery
  ): Observable<ObjectRelationInstancesResponse> {
    const httpParams = new HttpParams()
      .set('relation_id', query.relationId.toString())
      .set('role', query.role)
      .set('page', query.page.toString())
      .set('limit', query.limit.toString())
      .set('sort', query.sort)
      .set('order', query.order.toString());

    const options = { ...this.options, params: httpParams };
    return this.api.callGet<any>(`${this.servicePrefix}/tabs/${objectID}/instances`, options).pipe(
      map((apiResponse: HttpResponse<ObjectRelationInstancesResponse>) => ({
        total: apiResponse.body?.total ?? 0,
        count: apiResponse.body?.count ?? 0,
        results: apiResponse.body?.results ?? []
      }))
    );
  }


  // Get single object relation by ID
  public getObjectRelation(publicID: number): Observable<any> {
    const options = { ...this.options, params: new HttpParams() };
    return this.api.callGet<any>(`${this.servicePrefix}/${publicID}`, options).pipe(
      map((apiResponse: HttpResponse<APIGetSingleResponse<any>>) =>
        apiResponse.body.result
      )
    );
  }


  // Create new object relation
  public postObjectRelation(dto: CmdbObjectRelationCreateDto): Observable<any> {
    const options = { ...this.options };
    return this.api.callPost<any>(this.servicePrefix + '/', dto, options).pipe(
      map((httpResp: HttpResponse<APIInsertSingleResponse<any>>) =>
        httpResp.body.raw
      )
    );
  }

  // Update existing object relation
  public putObjectRelation(
    publicID: number,
    dto: Partial<CmdbObjectRelationCreateDto>
  ): Observable<any> {
    const options = { ...this.options };
    return this.api.callPut<any>(
      `${this.servicePrefix}/${publicID}`,
      dto,
      options
    ).pipe(
      map((apiResponse: HttpResponse<APIUpdateSingleResponse<any>>) =>
        apiResponse.body.result
      )
    );
  }

  // Delete object relation by ID
  public deleteObjectRelation(publicID: number): Observable<any> {
    const options = { ...this.options };
    return this.api.callDelete<any>(
      `${this.servicePrefix}/${publicID}`,
      options
    ).pipe(
      map((apiResponse: HttpResponse<APIDeleteSingleResponse<any>>) =>
        apiResponse.body.raw
      )
    );
  }

  // Delete multiple object relations by IDs
  public deleteManyObjectRelations(targetIDs: number[]): Observable<boolean> {
    const options = { ...this.options };
    const payload = { target_ids: targetIDs };

    return this.api.callPost<any>(
      `${this.servicePrefix}/delete/many`,
      payload,
      options
    ).pipe(
      map((apiResponse: HttpResponse<any>) => Boolean(apiResponse?.body?.success))
    );
  }
}
