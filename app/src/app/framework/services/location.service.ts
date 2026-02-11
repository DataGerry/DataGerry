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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

import { Injectable } from '@angular/core';
import { HttpHeaders, HttpParams, HttpResponse } from '@angular/common/http';
import { UntypedFormControl } from '@angular/forms';

import { Observable, timer, Subject } from 'rxjs';
import { catchError, map, switchMap, finalize } from 'rxjs/operators';

import { ApiCallService, ApiServicePrefix, resp } from '../../services/api-call.service';

import { CmdbLocation } from '../models/cmdb-location';
import { RenderResult } from '../models/cmdb-render';
import { CollectionParameters } from '../../services/models/api-parameter';
import { APIGetMultiResponse, APIUpdateSingleResponse } from '../../services/models/api-response';
/* ------------------------------------------------------------------------------------------------------------------ */

// export const checkLocationExistsValidator = (locationService: LocationService, time: number = 500) => {
//   return (control: UntypedFormControl) => {
//     return timer(time).pipe(switchMap(() => {
//       return locationService.getLocation(+control.value).pipe(
//         map((response) => {
//           if (response === null) {
//             return { locationExists: true };
//           } else {
//             return null;
//           }
//         }),
//         catchError((e) => {
//           return new Promise(resolve => {
//             if (e.status === 403) {
//               resolve({ locationProtected: true });
//             }
//             resolve({ locationExists: true });
//           });
//         })
//       );
//     }));
//   };
// };

// export const httpLocationObserveOptions = {
//   headers: new HttpHeaders({
//     'Content-Type': 'application/json'
//   }),
//   observe: resp
// };

export const PARAMETER = 'params';
export const COOCKIENAME = 'onlyActiveObjCookie';

@Injectable({
  providedIn: 'root'
})
export class LocationService<T = CmdbLocation | RenderResult> implements ApiServicePrefix {

    public servicePrefix: string = 'locations';

    public locationActionSource = new Subject();

    public readonly options = {
        headers: new HttpHeaders({
            'Content-Type': 'application/json'
        }),
        params: {},
        observe: resp
    };

    /**TODO: temporary used for creation of new objects, will be refactored in future */
    public locationTreeName: string = "";

    constructor(private api: ApiCallService) {

    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                   CRUD - SECTION                                                   */
/* ------------------------------------------------------------------------------------------------------------------ */


/* -------------------------------------------------- CRUD - CREATE ------------------------------------------------- */


    /**
     * Creates and stores a CmdbLocation in the database
     * 
     * @param objectInstance (CmdbLocation): location which should be crated
     * @returns Observable<any>
     */
    public postLocation(params): Observable<any> {

      const postOptions = this.options;
      let httpParams = new HttpParams();

      for (let key in params){
        let val:string = String(params[key]);
        httpParams = httpParams.set(key, val);
      }

      postOptions.params = httpParams;

      return this.api.callPost<CmdbLocation>(this.servicePrefix + '/', params , postOptions).pipe(
          map((apiResponse) => {
          return apiResponse.body;
          }),
          finalize(() => this.executedAction('create'))
      );
  }


/* --------------------------------------------------- CRUD - READ -------------------------------------------------- */


    /**
     * Retrieves all locations with the given parameters
     * 
     * @param params (CollectionParameters): parameters for db call
     * @param view (string): view mode ('native' or 'render')
     * @returns Observable<APIGetMultiResponse<T>>
     */
    public getLocations(
        params: CollectionParameters = {
            filter: undefined, 
            limit: 0, 
            sort: 'public_id',
            order: 1, 
            page: 1, 
            projection: undefined 
        },
        view: string = 'render'): Observable<APIGetMultiResponse<T>> {
            const options = this.options;
            let httpParams: HttpParams = new HttpParams();
            if (params.filter !== undefined) {
            const filter = JSON.stringify(params.filter);
            httpParams = httpParams.set('filter', filter);
            }
            if (params.projection !== undefined) {
            const projection = JSON.stringify(params.projection);
            httpParams = httpParams.set('projection', projection);
            }
            httpParams = httpParams.set('limit', params.limit.toString());
            httpParams = httpParams.set('sort', params.sort);
            httpParams = httpParams.set('order', params.order.toString());
            httpParams = httpParams.set('page', params.page.toString());

            httpParams = httpParams.set('view', view);
            httpParams = httpParams.set('onlyActiveObjCookie', this.api.readCookies(COOCKIENAME));
            options.params = httpParams;

            return this.api.callGet<Array<T>>(this.servicePrefix + '/', options).pipe(
                map((apiResponse: HttpResponse<APIGetMultiResponse<T>>) => {
                    return apiResponse.body;
                })
            );
    }


    public getLocationsTree(
                  params: CollectionParameters = {
                    filter: undefined, 
                    limit: 0, 
                    sort: 'public_id',
                    order: 1, 
                    page: 1, 
                    projection: undefined 
                },
                view: string = 'render'): Observable<APIGetMultiResponse<T>> {
        const options = this.options;
        let httpParams: HttpParams = new HttpParams();
        if (params.filter !== undefined) {
        const filter = JSON.stringify(params.filter);
        httpParams = httpParams.set('filter', filter);
        }
        if (params.projection !== undefined) {
        const projection = JSON.stringify(params.projection);
        httpParams = httpParams.set('projection', projection);
        }
        httpParams = httpParams.set('limit', params.limit.toString());
        httpParams = httpParams.set('sort', params.sort);
        httpParams = httpParams.set('order', params.order.toString());
        httpParams = httpParams.set('page', params.page.toString());

        httpParams = httpParams.set('view', view);
        httpParams = httpParams.set('onlyActiveObjCookie', this.api.readCookies(COOCKIENAME));
        options.params = httpParams;

        return this.api.callGet<Array<T>>(this.servicePrefix + '/tree', options).pipe(
            map((apiResponse: HttpResponse<APIGetMultiResponse<T>>) => {
                return apiResponse.body;
            })
        );
    }


    /**
     * Retrieves a location with given public_id
     * 
     * @param publicID (int): public_id of the location
     * @param native (boolean): return native or not
     * @returns Observable<R>
     */
    public getLocation<R>(publicID: number, native: boolean = false): Observable<R> {
        const options = this.options;
        options.params = new HttpParams();

        if (native === true) {
            return this.api.callGet<CmdbLocation[]>(`${ this.servicePrefix }/${ publicID }`, options).pipe(
                map((apiResponse) => {
                    return apiResponse.body;
                })
            );
        }

        return this.api.callGet<R[]>(`${ this.servicePrefix }/${ publicID }`, options).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            })
        );
    }


   /**
   * Retrieves the location for the object with the given object_id
   * 
   * @param objectID (int): object_id of the location
   * @param native (boolean): return native or not
   * @returns Observable<R>
   */
    public getLocationForObject<R>(objectID: number, native: boolean = false): Observable<R> {
        const options = this.options;
        options.params = new HttpParams();

        if (native === true) {
            return this.api.callGet<CmdbLocation[]>(`${ this.servicePrefix }/${ objectID }/object`, options).pipe(
                map((apiResponse) => {
                    return apiResponse.body;
                })
            );
        }

        return this.api.callGet<R[]>(`${ this.servicePrefix }/${ objectID }/object`, options).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            })
        );
    }


  /**
   * Retrieves the location for the object with the given object_id
   * 
   * @param objectID (int): object_id of the location
   * @param native (boolean): return native or not
   * @returns Observable<R>
   */
    public getParent<R>(objectID: number, native: boolean = false): Observable<R> {
      const options = this.options;
      options.params = new HttpParams();

      if (native === true) {
          return this.api.callGet<CmdbLocation[]>(`${ this.servicePrefix }/${ objectID }/parent`, options).pipe(
              map((apiResponse) => {
                  return apiResponse.body;
              })
          );
      }

      return this.api.callGet<R[]>(`${ this.servicePrefix }/${ objectID }/parent`, options).pipe(
          map((apiResponse) => {
              return apiResponse.body;
          })
      );
    }


    /**
     * Retrieves the next level of children for the object with the given object_id
     * 
     * @param objectID (int): object_id of the location
     * @returns Observable<R>
     */
    public getChildren<R>(objectID: number): Observable<R> {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callGet<R[]>(`${ this.servicePrefix }/${ objectID }/children`, options).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            })
        );
    }


/* -------------------------------------------------- CRUD - UPDATE ------------------------------------------------- */

    /**
     * Updates a CmdbLocation in the database
     * 
     * @param publicID (int): public_id of the location
     * @param objectInstance (CmdbLocation): the data which should be updated
     * @param httpOptions httpObserveOptions
     * @returns Observable<any>
     */
    public updateLocationForObject(params): Observable<any> {

        const putOptions = this.options;
        let httpParams = new HttpParams();

        for (let key in params){
          let val:string = String(params[key]);
          httpParams = httpParams.set(key, val);
        }

        putOptions.params = httpParams;

        return this.api.callPut<T>(`${ this.servicePrefix }/update_location`, params, putOptions).pipe(
            map((apiResponse: HttpResponse<APIUpdateSingleResponse<T>>) => {
                return apiResponse.body;
            }),
            finalize(() => this.executedAction('update'))
        );
    }


/* -------------------------------------------------- CRUD - DELETE ------------------------------------------------- */

    /**
     * Deletes a location from the database with the given public_id
     * 
     * @param publicID (int): public_id of location which should be deleted
     * @returns Observable<any>
     */

    //TODO: not implemented on backend - start
    // public deleteLocation(publicID: any): Observable<any> {
        

    //     const options = this.options;
    //     options.params = new HttpParams();

    //     return this.api.callDelete(`${ this.servicePrefix }/${ publicID }`, options).pipe(
    //         map((apiResponse) => {
    //             return apiResponse.body;
    //         })
    //     );
    // }

    /**
     * Deletes a location from the database where the object_id matches the given objectID
     * 
     * @param objectID publicID of object for which the location should be deleted
     * @returns Observable<any>
     */
    public deleteLocationForObject(objectID: any): Observable<any> {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callDelete(`${ this.servicePrefix }/${ objectID }/object`, options).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            }),
            finalize(() => this.executedAction('delete'))
        );
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                   HELPER SECTION                                                   */
/* ------------------------------------------------------------------------------------------------------------------ */


    /**
     * Extracts all children for a given public_id of a location from the locationsList
     * 
     * @param publicID public_id of the location for which the children should be searched
     * @param locationsList list of locations where the children should be searched
     * @returns (list): All found children
     */
    public extractAllChildren(publicID: number, locationsList){
      let foundChildren = [];
      let recursiveChildren = [];
      let allChildren = [];
      
      //add direct children
      for (let location of locationsList){
          if (location['parent'] == publicID){
            foundChildren.push(location);
          }
      }

      //search recursive for all children
      if(foundChildren.length > 0){
        for(let child of foundChildren){
            allChildren.push(child);

            recursiveChildren = this.extractAllChildren(child['public_id'], locationsList);

            if(recursiveChildren.length > 0){
              for (let recChild of recursiveChildren){
                allChildren.push(recChild);
              }
            }
        }
      }

      return allChildren;
    }


    /**
     * Notifies subscribers that an operation was executed by the LocationService
     * 
     * @param action (string): Which operation was executed (create, update, delete)
     */
    executedAction(action: string){
        this.locationActionSource.next(action);
    }

}
