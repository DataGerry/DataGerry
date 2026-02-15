// src/app/services/base-api.service.ts
import { Injectable } from '@angular/core';
import { HttpHeaders, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map, catchError } from 'rxjs/operators';
import { ApiServicePrefix, ApiCallService, resp } from 'src/app/services/api-call.service';
import { CollectionParameters } from 'src/app/services/models/api-parameter';



@Injectable()
export abstract class BaseApiService<TModel> implements ApiServicePrefix {
  public abstract servicePrefix: string;
  protected readonly defaultHeaders = new HttpHeaders({ 'Content-Type': 'application/json' });

  constructor(protected api: ApiCallService) { }

  protected get httpOptions() {
    return {
      headers: this.defaultHeaders,
      params: new HttpParams(),
      observe: resp
    };
  }


  /**
   * Fetch a list of items with pagination, filtering, and sorting
   * @param params CollectionParameters
   * @return Observable<APIGetMultiResponse<TModel>>
   */
  protected buildHttpParams(params: CollectionParameters): HttpParams {
    let httpParams = new HttpParams()
      .set('limit', params.limit.toString())
      .set('page', params.page.toString())
      .set('sort', params.sort)
      .set('order', params.order.toString());

    if (params.filter) {
      httpParams = httpParams.set('filter', JSON.stringify(params.filter));
    }
    return httpParams;
  }

  protected extractBody<T>(res: { body?: T } | null | undefined): T {
    return (res && res.body !== undefined ? res.body : (null as unknown as T));
  }

  /**
   * Handle GET request
   * @param params CollectionParameters
   * @return Observable<APIGetMultiResponse<TModel>>
   */
  protected handleGetRequest<T>(url: string, params?: HttpParams): Observable<T> {
    const options = { ...this.httpOptions, params };
    return this.api.callGet<T>(url, options).pipe(
      map((res) => this.extractBody<T>(res)),
      catchError((error) => { throw error; })
    );
  }


  /**
   * Handle POST request
   * @param url string
   * @param body any
   * @return Observable<T>
   */
  protected handlePostRequest<T>(url: string, body: any): Observable<T> {
    return this.api.callPost<T>(url, body, this.httpOptions).pipe(
      map((res) => this.extractBody<T>(res)),
      catchError((error) => { throw error; })
    );
  }


  /**
   * Handle PUT request
   * @param url string
   * @param body any
   * @return Observable<T>
   */
  protected handlePutRequest<T>(url: string, body: any): Observable<T> {
    return this.api.callPut<T>(url, body, this.httpOptions).pipe(
      map((res) => this.extractBody<T>(res)),
      catchError((error) => { throw error; })
    );
  }


  /**
   * Handle DELETE request
   * @param url string
   * @return Observable<T>
   */
  protected handleDeleteRequest<T>(url: string): Observable<T> {
    return this.api.callDelete<T>(url, this.httpOptions).pipe(
      map((res) => this.extractBody<T>(res)),
      catchError((error) => { throw error; })
    );
  }
}