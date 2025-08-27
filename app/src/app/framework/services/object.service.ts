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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Injectable } from '@angular/core';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { HttpHeaders, HttpParams, HttpResponse } from '@angular/common/http';
import { UntypedFormControl } from '@angular/forms';

import { BehaviorSubject, Observable, of, Subject, throwError, timer } from 'rxjs';
import { catchError, map, switchMap, finalize, shareReplay } from 'rxjs/operators';

import { ApiCallService, ApiServicePrefix, httpObserveOptions, resp } from '../../services/api-call.service';

import { CmdbObject } from '../models/cmdb-object';
import { RenderResult } from '../models/cmdb-render';
import { GeneralModalComponent } from '../../layout/helpers/modals/general-modal/general-modal.component';
import { CollectionParameters } from '../../services/models/api-parameter';
import { APIGetListResponse, APIGetMultiResponse, APIUpdateMultiResponse } from '../../services/models/api-response';
import { CmdbType } from '../models/cmdb-type';
import { LocationsModalComponent } from 'src/app/layout/helpers/modals/locations-modal/locations-modal.component';
import { UserService } from 'src/app/management/services/user.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
/* -------------------------------------------------------------------------- */

export const checkObjectExistsValidator = (objectService: ObjectService, time: number = 500) => {
    return (control: UntypedFormControl) => {
        const value = control.value;
        if (!value) {
            return of(null);
        }
        return timer(time).pipe(switchMap(() => {
            return objectService.getObject(+control.value).pipe(
                map((response) => {
                    if (response === null) {
                        return { objectExists: true };
                    } else {
                        return null;
                    }
                }),
                catchError((e) => {
                    return new Promise(resolve => {
                        if (e.status === 403) {
                            resolve({ objectProtected: true });
                        }

                        resolve({ objectExists: true });
                    });
                })
            );
        }));
    };
};


export const httpObjectObserveOptions = {
    headers: new HttpHeaders({
        'Content-Type': 'application/json'
    }),
    observe: resp
};

export const PARAMETER = 'params';
export const COOCKIENAME = 'onlyActiveObjCookie';

@Injectable({
    providedIn: 'root'
})
export class ObjectService<T = CmdbObject | RenderResult> implements ApiServicePrefix {
    public objectActionSource = new Subject();
    public servicePrefix: string = 'objects';


    // A private property to store the last fetched count
    private lastObjectCountSubject = new BehaviorSubject<number>(0);

    public readonly options = {
        headers: new HttpHeaders({
            'Content-Type': 'application/json'
        }),
        params: {},
        observe: resp
    };

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(private api: ApiCallService, private modalService: NgbModal, private userService: UserService) {

    }


    /* -------------------------------------------------- CRUD - CREATE ------------------------------------------------- */

    public postObject(objectInstance: CmdbObject): Observable<any> {
        const options = this.options;
        options.params = new HttpParams();
        return this.api.callPost<CmdbObject>(this.servicePrefix + '/', objectInstance, options).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            }),
            finalize(() => this.executedAction('create'))
        );
    }

    /* --------------------------------------------------- CRUD - READ -------------------------------------------------- */

    public getObjects(
        params: CollectionParameters = {
            filter: undefined,
            limit: 10,
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


    public getObjectsByType(typeID: number | Array<number>): Observable<Array<T>> {

        if (!Array.isArray(typeID)) {
            typeID = [typeID];
        }

        const options = this.options;
        let httpParams: HttpParams = new HttpParams();
        const filter = JSON.stringify({ type_id: { $in: typeID } });
        httpParams = httpParams.set('filter', filter);
        httpParams = httpParams.set('limit', '0');
        httpParams = httpParams.set('view', 'render');
        httpParams = httpParams.set('onlyActiveObjCookie', this.api.readCookies(COOCKIENAME));
        options.params = httpParams;

        return this.api.callGet<Array<T>>(this.servicePrefix + '/', options).pipe(
            map((apiResponse: HttpResponse<APIGetMultiResponse<T>>) => {
                return apiResponse.body.results as Array<T>;
            })
        );
    }


    public getObject<R>(publicID: number, native: boolean = false): Observable<R> {

        const options = this.options;
        options.params = new HttpParams();
        if (native === true) {
            return this.api.callGet<CmdbObject[]>(`${this.servicePrefix}/native/${publicID}`, options).pipe(
                map((apiResponse) => {
                    return apiResponse.body;
                })
            );
        }

        return this.api.callGet<R[]>(`${this.servicePrefix}/${publicID}`, options).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            })
        );
    }


    public getObjectMdsReference<R>(publicID: number): Observable<R> {

        const options = this.options;
        options.params = new HttpParams();

        return this.api.callGet<R[]>(`${this.servicePrefix}/${publicID}/mds_reference`, options).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            })
        );
    }


    public getObjectMdsReferences<R>(publicID: number, objectIDs: any): Observable<R> {
        const options = this.options;

        let httpParams = new HttpParams();
        httpParams = httpParams.set('objectIDs', objectIDs);
        options.params = httpParams;

        return this.api.callGet<R[]>(`${this.servicePrefix}/${publicID}/mds_references`, options).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            })
        );
    }


    /**
     * Get the newest objects
     * @param params
     * @param view
     */
    public getNewestObjects<R>(
        params: CollectionParameters = { limit: 10, order: -1, page: 1 },
        view: string = 'render'): Observable<APIGetMultiResponse<T>> {

        params.sort = 'creation_time';
        params.filter = [{ $match: { creation_time: { $ne: null } } }];

        return this.getObjects(params, view);
    }


    /**
     * Get the latest objects
     * @param params
     * @param view
     */
    public getLatestObjects<R>(
        params: CollectionParameters = { limit: 10, order: -1, page: 1 },
        view: string = 'render'): Observable<APIGetMultiResponse<T>> {

        params.sort = 'last_edit_time';
        params.filter = [{ $match: { last_edit_time: { $ne: null } } }];

        return this.getObjects(params, view);
    }


    public changeState(publicID: number, status: boolean) {
        const options = this.options;
        options.params = new HttpParams();
        return this.api.callPut<boolean>(`${this.servicePrefix}/state/${publicID}`, status, options).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            }),
            finalize(() => this.executedAction('update'))
        );
    }


    /**
     * Fetches the total count of objects from the server using a HEAD request.
     * @returns An observable that emits the total object count.
     */
    public countObjects<T>(): Observable<number> {
        const options = this.options;
        options.params = new HttpParams();
        return this.api.callGet<any>(this.servicePrefix + '/count', options).pipe(
            map((count: any) => {
                
                count = +count.body;
                this.lastObjectCountSubject.next(count);
                return count;
            })
        );
    }


    /**
     * Returns an observable for the last fetched object count.
     * Components can subscribe to this and react to updates without another backend call.
     */
    public getLastObjectCount(): Observable<number> {
        return this.lastObjectCountSubject.asObservable();
    }


    public countObjectsByType(typeID: number | Array<number>): Observable<number> {
        if (!Array.isArray(typeID)) {
            typeID = [typeID];
        }

        const options = this.options;
        let httpParams: HttpParams = new HttpParams();
        const filter = JSON.stringify({ type_id: { $in: typeID } });
        httpParams = httpParams.set('filter', filter);
        httpParams = httpParams.set('limit', '0');
        httpParams = httpParams.set('onlyActiveObjCookie', this.api.readCookies(COOCKIENAME));
        options.params = httpParams;

        return this.api.callHead<Array<T>>(this.servicePrefix + '/', options).pipe(
            map((apiResponse: HttpResponse<APIGetMultiResponse<T>>) => {
                return +apiResponse.headers.get('X-Total-Count');
            })
        );
    }


    public groupObjectsByType(value: string) {
        httpObjectObserveOptions[PARAMETER] = { onlyActiveObjCookie: this.api.readCookies(COOCKIENAME) };

        return this.api.callGet<any>(this.servicePrefix + '/group/' + value, httpObjectObserveOptions).pipe(
            map((apiResponse) => {
                if (apiResponse.status === 204) {
                    return [];
                }

                return apiResponse.body;
            })
        );
    }


    /**
     * API call to get iterable objects which referer to a object.
     * @param publicID of the referenced object.
     * @param params collection iteration parameters
     * @param view
     */
    public getObjectReferences<R = T>(publicID: number,
        params: CollectionParameters = {
            filter: undefined,
            limit: 10,
            sort: 'public_id',
            order: 1,
            page: 1
        },
        view: string = 'render'): Observable<APIGetMultiResponse<T>> {
        const options = this.options;
        let httpParams: HttpParams = new HttpParams();

        if (params.filter !== undefined) {
            const filter = JSON.stringify(params.filter);
            httpParams = httpParams.set('filter', filter);
        }

        httpParams = httpParams.set('limit', params.limit.toString());
        httpParams = httpParams.set('sort', params.sort);
        httpParams = httpParams.set('order', params.order.toString());
        httpParams = httpParams.set('page', params.page.toString());
        httpParams = httpParams.set('onlyActiveObjCookie', this.api.readCookies(COOCKIENAME));
        httpParams = httpParams.set('view', view);
        options.params = httpParams;

        return this.api.callGet<Array<R>>(`${this.servicePrefix}/references/${publicID}`, options).pipe(
            map((apiResponse: HttpResponse<APIGetMultiResponse<T>>) => {
                return apiResponse.body;
            })
        );
    }

    /* -------------------------------------------------- CRUD - UPDATE ------------------------------------------------- */

    public putObject(publicID: number, objectInstance: CmdbObject, httpOptions = httpObserveOptions): Observable<any> {
        return this.api.callPut<T>(`${this.servicePrefix}/${publicID}`, objectInstance, httpOptions).pipe(
            map((apiResponse: HttpResponse<APIUpdateMultiResponse<T>>) => {
                return apiResponse.body;
            }),
            finalize(() => this.executedAction('update'))
        );
    }

    /* -------------------------------------------------- CRUD - DELETE ------------------------------------------------- */

    public deleteManyObjects(publicID: any) {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callDeleteManyRoute(`${this.servicePrefix}/delete/${publicID}`, options).pipe(
            map((apiResponse) => {
                if (apiResponse.status === 204) {
                    return [];
                }

                return apiResponse.body;
            }),
            finalize(() => this.executedAction('delete'))
        );
    }

    /**
     * Delete an object with the given public_id
     * @param publicID public_id of object which should be deleted
     * @returns 
     */
    public deleteObject(publicID: any): Observable<any> {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callDelete(`${this.servicePrefix}/${publicID}`, options).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            }),
            finalize(() => this.executedAction('delete'))
        );
    }


    public deleteObjectWithLocations(publicID: any): Observable<any> {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callDelete(`${this.servicePrefix}/${publicID}/locations`, options).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            }),
            finalize(() => this.executedAction('delete'))
        );
    }


    public deleteObjectWithChildren(publicID: any): Observable<any> {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callDelete(`${this.servicePrefix}/${publicID}/children`, options).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            }),
            finalize(() => this.executedAction('delete'))
        );
    }

    /* ------------------------------------------------- UNCLEAN OBJECTS ------------------------------------------------ */

    public countUncleanObjects(typeID: number): Observable<number> {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callHead<CmdbType>(`${this.servicePrefix}/clean/${typeID}`, options).pipe(
            map((apiResponse: HttpResponse<APIGetListResponse<CmdbObject>>) => {
                return +apiResponse.headers.get('X-Total-Count');
            })
        );
    }


    public getUncleanObjects(typeID: number): Observable<Array<CmdbObject>> {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callGet<CmdbType>(`${this.servicePrefix}/clean/${typeID}`, options).pipe(
            map((apiResponse: HttpResponse<APIGetListResponse<CmdbObject>>) => {
                return apiResponse.body.results as Array<CmdbObject>;
            })
        );
    }


    public getObjectCleanStatus(typeID: number): Observable<boolean> {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callHead<CmdbType>(`${this.servicePrefix}/clean/${typeID}`, options).pipe(
            map((apiResponse) => {
                return +apiResponse.headers.get('X-Total-Count') === 0;
            })
        );
    }


    public cleanObjects(typeID: number): Observable<any> {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callPatch(`${this.servicePrefix}/clean/${typeID}`, null, options).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            })
        );
    }

    /* ------------------------------------------------------------------------------------------------------------------ */
    /*                                                    MODAL SECTION                                                   */
    /* ------------------------------------------------------------------------------------------------------------------ */

    public openModalComponent(title: string,
        modalMessage: string,
        buttonDeny: string,
        buttonAccept: string) {

        const modalComponent = this.modalService.open(GeneralModalComponent);
        modalComponent.componentInstance.title = title;
        modalComponent.componentInstance.modalMessage = modalMessage;
        modalComponent.componentInstance.buttonDeny = buttonDeny;
        modalComponent.componentInstance.buttonAccept = buttonAccept;

        return modalComponent;
    }


    /**
     * Open a modal confirmation for deletion when the object has a location which is
     * parent to other locations
     * 
     * @returns 
     */
    public openLocationModalComponent() {
        return this.modalService.open(LocationsModalComponent);
    }

    /* ------------------------------------------------------------------------------------------------------------------ */
    /*                                                   HELPER SECTION                                                   */
    /* ------------------------------------------------------------------------------------------------------------------ */

    /**
     * Notifies subscribers that an operation was executed by the ObjectService
     * 
     * @param action (string): Which operation was executed (create, update, delete)
     */
    executedAction(action: string) {
        this.objectActionSource.next(action);

        // After create or delete, fetch the updated count
        if (action === 'create' || action === 'delete') {
            this.countObjects().subscribe();
        }
    }


    /**
     * Get the config_items_limit value.
     * Fetches the value once and caches it for future use.
     */
    public getConfigItemsLimit(): Observable<number> {
        return this.userService.getUser(this.userService.getCurrentUser().public_id).pipe(
            map(user => {
                if (user && user.config_items_limit !== undefined) {
                    return user.config_items_limit;
                } else {
                    throw new Error('config_items_limit not found');
                }
            }),
            catchError(error => {
                return throwError(() => error);
            })
        );
    }

}
