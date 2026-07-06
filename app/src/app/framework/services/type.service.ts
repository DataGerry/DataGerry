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
import { UntypedFormControl } from '@angular/forms';
import { HttpHeaders, HttpParams, HttpResponse } from '@angular/common/http';

import { Observable, timer, catchError, map, switchMap } from 'rxjs';

import { ApiCallService, ApiServicePrefix, HttpProtocolHelper, resp } from '../../services/api-call.service';
import { ValidatorService } from '../../services/validator.service';
import { UserService } from '../../management/services/user.service';
import { SidebarService } from 'src/app/layout/services/sidebar.service';

import { CmdbType } from '../models/cmdb-type';
import { LocationFieldUsageResponse } from '../models/location-field-usage';
import {
  APIDeleteSingleResponse,
  APIGetMultiResponse,
  APIGetSingleResponse,
  APIInsertSingleResponse,
  APIUpdateSingleResponse
} from '../../services/models/api-response';
import { CollectionParameters } from '../../services/models/api-parameter';
import { AccessControlPermission } from 'src/app/modules/acl/acl.types';
/* ------------------------------------------------------------------------------------------------------------------ */

    export const checkTypeExistsValidator = (typeService: TypeService, time: number = 500) => {
        return (control: UntypedFormControl) => {
            return timer(time).pipe(switchMap(() => {
                return typeService.getTypeByName(control.value).pipe(
                        map((response) => {
                        if (response === null) {
                            return null;
                        } else {
                            return { typeExists: true };
                        }
                        }),
                        catchError(() => {
                        return new Promise(resolve => {
                            resolve(null);
                        });
                    })
                );
            }));
        };
    };


@Injectable({
    providedIn: 'root'
})
export class TypeService<T = CmdbType> implements ApiServicePrefix {

    public servicePrefix: string = 'types';
    
    public options = {
        headers: new HttpHeaders({
            'Content-Type': 'application/json'
        }),
        params: {},
        observe: resp
    };

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */
    constructor(private api: ApiCallService,
                private userService: UserService,
                private sideBarService: SidebarService) {

    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    /**
     * Returns acl read filter
     *
     * @public
     */
    public getAclFilter(aclRequirement: AccessControlPermission | AccessControlPermission[] = AccessControlPermission.READ) {
        aclRequirement = Array.isArray(aclRequirement) ? aclRequirement : [aclRequirement];
        const location = 'acl.groups.includes.' + this.userService.getCurrentUser().group_id;

        return {
            $or: [
                {
                    $or: [
                        {
                            acl: { $exists: false } 
                        },
                        {
                            'acl.activated': false
                        }
                    ]
                },
                {
                    $and: [
                        {
                            'acl.activated': true
                        },
                        {
                            $and: [
                                {
                                    [location]: {
                                        $exists: true
                                    }
                                },
                                {
                                    [location]: {
                                        $all: aclRequirement
                                    }
                                }
                            ]
                        },
                    ]
                }
            ]
        };
    }


    /**
     * Iterate over the type collection
     * @param params Instance of CollectionParameters
     * @param active Filter types by activation status. Default: Inactive types are not fetched
     */
    public getTypes(
        params: CollectionParameters = {filter: undefined, limit: 10, sort: 'public_id', order: 1, page: 1},
        active: boolean = false): Observable<APIGetMultiResponse<T>> {

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
            httpParams = httpParams.set('active', JSON.stringify(active));
            options.params = httpParams;

            return this.api.callGet<Array<T>>(this.servicePrefix + '/', options).pipe(
                map((apiResponse: HttpResponse<APIGetMultiResponse<T>>) => {
                    return apiResponse.body;
                })
            );
    }


    /**
     * Iterate over the type collection and include object clean status.
     * @param params Instance of CollectionParameters
     * @param active Filter types by activation status. Default: Inactive types are not fetched
     */
    public getTypesWithCleanStatus(
        params: CollectionParameters = { filter: undefined, limit: 10, sort: 'public_id', order: 1, page: 1 },
        active: boolean = false
    ): Observable<APIGetMultiResponse<{ type_data: T; clean_status: boolean }>> {
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
        httpParams = httpParams.set('active', JSON.stringify(active));
        options.params = httpParams;

        return this.api.callGet<Array<{ type_data: T; clean_status: boolean }>>(`${this.servicePrefix}/with_clean_status`, options).pipe(
            map((apiResponse: HttpResponse<APIGetMultiResponse<{ type_data: T; clean_status: boolean }>>) => {
                return apiResponse.body;
            })
        );
    }


    /**
     * Checks whether the location field of a given type is currently in use by any objects.
     *
     * @param publicID PublicID of the type
     * @returns Observable resolving to { in_use, count, object_public_ids }
     */
    public getLocationFieldUsage(publicID: number): Observable<LocationFieldUsageResponse> {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callGet<LocationFieldUsageResponse>(`${this.servicePrefix}/location_field_usage/${publicID}`, options).pipe(
            map((apiResponse: HttpResponse<LocationFieldUsageResponse>) => apiResponse.body)
        );
    }


    /**
     * Get a specific type by the id
     * @param publicID PublicID of the type
     */
    public getType(publicID: number): Observable<T> {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callGet<CmdbType>(this.servicePrefix + '/' + publicID, options).pipe(
            map((apiResponse: HttpResponse<APIGetSingleResponse<T>>) => {
                return apiResponse.body.result as T;
            })
        );
    }


    /**
     * Get the complete type list
     */
    public getTypeList(aclRequirement?: AccessControlPermission | AccessControlPermission[]): Observable<Array<T>> {
        const options = this.options;
        let params = new HttpParams();
        params = params.set('limit', '0');
        params = params.set('filter', JSON.stringify(this.getAclFilter(aclRequirement)));
        options.params = params;

        return this.api.callGet<Array<T>>(this.servicePrefix + '/', options).pipe(
            map((apiResponse: HttpResponse<APIGetMultiResponse<T>>) => {
                return apiResponse.body.results as Array<T>;
            })
        );
    }


    /**
     * Get types by the name or label
     * @param name Name of the type
     */
    public getTypeByName(name: string): Observable<T> {
        const options = this.options;
        const filter = { name };
        let params: HttpParams = new HttpParams();
        params = params.set('filter', JSON.stringify(filter));
        options.params = params;

        return this.api.callGet<Array<T>>(this.servicePrefix + '/', options).pipe(
            map((apiResponse: HttpResponse<APIGetMultiResponse<T>>) => {
                if (apiResponse.body.count === 0) {
                    return null;
                }

                return apiResponse.body.results[0] as T;
            })
        );
    }


    /**
     * Get types by the name or label
     * @param name Name/Label of the type
     * @param aclRequirements
     */
    public getTypesByNameOrLabel(name: string, aclRequirements?: AccessControlPermission | AccessControlPermission[]):
            Observable<Array<T>> {

                const regex = ValidatorService.validateRegex(name).trim();

                const filter = {
                    $and: [
                        {
                            $or: [
                                { name: { $regex: regex, $options: 'ism' } },
                                { label: { $regex: regex, $options: 'ism' } }
                            ]
                        },
                        this.getAclFilter(aclRequirements)
                    ]
                };

                const options = HttpProtocolHelper.createHttpProtocolOptions(this.options, JSON.stringify(filter), 0);

                return this.api.callGet<Array<T>>(this.servicePrefix + '/', options).pipe(
                    map((apiResponse: HttpResponse<APIGetMultiResponse<T>>) => {
                        return apiResponse.body.results as Array<T>;
                    })
                );
    }


    /**
     * Insert a new type into the database.
     */
    public postType(type: CmdbType): Observable<T> {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callPost<T>(this.servicePrefix + '/', type, options).pipe(
            map((apiResponse: HttpResponse<APIInsertSingleResponse<T>>) => {
                return apiResponse.body.raw as T;
            })
        );
    }


    /**
     * Update a existing type in the database.
     */
    public putType(type: CmdbType): Observable<T> {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callPut<T>(this.servicePrefix + '/' + type.public_id, type, options).pipe(
            map((apiResponse: HttpResponse<APIUpdateSingleResponse<T>>) => {
                return apiResponse.body.result as T;
            })
        );
    }


    /**
     * Delete a existing type in the database.
     * @returns The deleted type instance.
     */
    public deleteType(publicID: number): Observable<T> {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callDelete<number>(this.servicePrefix + '/' + publicID, options).pipe(
            map((apiResponse: HttpResponse<APIDeleteSingleResponse<T>>) => {
                this.sideBarService.loadCategoryTree()
                return apiResponse.body.raw as T;
            })
        );
    }


    /**
     * Get all uncategorized types
     * @param aclRequirements
     * @param active filter types by activation status. Default: Active types are fetched
     */
    public getUncategorizedTypes(aclRequirements?: AccessControlPermission | AccessControlPermission[],
            active: boolean = true): Observable<APIGetMultiResponse<T>> {

            const pipeline = [
                {
                    $match: this.getAclFilter(aclRequirements)
                },
                {
                    $lookup: {
                        from: 'framework.categories',
                        localField: 'public_id',
                        foreignField: 'types',
                        as: 'categories'
                    }
                },
                {
                    $match: { categories: { $size: 0 } }
                },
                {
                    $project: { categories: 0 }
                }
            ];

            const options = HttpProtocolHelper.createHttpProtocolOptions(this.options, JSON.stringify(pipeline), 0);
            options.params = options.params.set('active', JSON.stringify(active));

            return this.api.callGet<T[]>(this.servicePrefix + '/', options).pipe(
                map((apiResponse: HttpResponse<APIGetMultiResponse<T>>) => {
                    return apiResponse.body as APIGetMultiResponse<T>;
                })
            );
    }


    /**
     * Get a list of types by the category
     * @param categoryID PublicID of the category
     * @param aclRequirements
     */
    public getTypeListByCategory(categoryID: number, aclRequirements?: AccessControlPermission | AccessControlPermission[]):
        Observable<Array<T>> {

            // Previous problematic pipeline (commented out for reference):
            // const pipeline = [
            //     {
            //         $lookup: {
            //             from: 'framework.categories',
            //             pipeline: [
            //                 { $match: { public_id: categoryID } },
            //                 { 
            //                     $addFields: { type_id: { $toInt: '$$ROOT.public_id' } } 
            //                 },
            //                 { $match: { $expr: { $in: ['$type_id', '$types'] } } }
            //             ],
            //             as: 'category'
            //         }
            //     },
            //     {
            //         $match: {
            //             $and: [
            //                 { 'category.0': { $exists: true } },
            //                 this.getAclFilter(aclRequirements)
            //             ]
            //         }
            //     },
            //     {
            //         $project: { category: 0 }
            //     }
            // ];
            //
            // Issue: The pipeline incorrectly used $$ROOT.public_id which referred to the category's public_id
            // instead of the type's public_id. This caused the lookup to fail when matching types against
            // the category's types array.

            // Corrected pipeline (active):
            const pipeline = [
                {
                    $lookup: {
                        from: 'framework.categories',
                        let: { type_public_id: '$public_id' },
                        pipeline: [
                            { $match: { public_id: categoryID } },
                            { $match: { $expr: { $in: ['$$type_public_id', '$types'] } } }
                        ],
                        as: 'category'
                    }
                },
                {
                    $match: {
                        $and: [
                            { 'category.0': { $exists: true } },
                            this.getAclFilter(aclRequirements)
                        ]
                    }
                },
                {
                    $project: { category: 0 }
                }
            ];

            const options = HttpProtocolHelper.createHttpProtocolOptions(this.options, JSON.stringify(pipeline), 0);
            options.params = options.params.set('active', false.toString());

            return this.api.callGet<Array<T>>(this.servicePrefix + '/', options).pipe(
                map((apiResponse: HttpResponse<APIGetMultiResponse<T>>) => {
                    return apiResponse.body.results as Array<T>;
                })
            );
    }


    /**
     * Get the total number of types in the system.
     */
    public countTypes(): Observable<number> {
        const options = this.options;
        options.params = new HttpParams();
        return this.api.callHead<T[]>(this.servicePrefix + '/', options).pipe(
        map((apiResponse: HttpResponse<APIGetMultiResponse<T>>) => {
            return +apiResponse.headers.get('X-Total-Count');
        })
        );
    }


    /**
     * Retrieves the number of objects with the given type_id
     * 
     * @param typeID (number): type_id for which the objects should be counted
     * @returns (Observable<number>): Number of objects with the given type_id
     */
    public countTypeObjects(typeID: number): Observable<number> {
        return this.api.callGet<number>(this.servicePrefix + '/count_objects/' + typeID, this.options).pipe(
            map((apiResponse: HttpResponse<number>) => {
                return apiResponse.body;
            })
        );
    }
}
