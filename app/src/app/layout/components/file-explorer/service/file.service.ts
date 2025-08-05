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

* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { Injectable } from '@angular/core';
import { Observable, timer } from 'rxjs';
import { catchError, map, switchMap } from 'rxjs/operators';
import { HttpHeaders, HttpParams, HttpResponse } from '@angular/common/http';
import { FileMetadata } from '../model/metadata';
import { UntypedFormControl } from '@angular/forms';
import { FileElement } from '../model/file-element';
import {APIGetMultiResponse, APIGetSingleResponse} from '../../../../services/models/api-response';
import {
  ApiCallService,
  ApiServicePrefix,
  httpFileOptions,
  httpObserveOptions,
  resp
} from '../../../../services/api-call.service';
import { ValidatorService } from '../../../../services/validator.service';

export const checkFolderExistsValidator = (fileService: FileService, metadata: any, time: number = 500) => {
  return (control: UntypedFormControl) => {
    return timer(time).pipe(switchMap(() => {
      return fileService.getFileElement(control.value, metadata).pipe(
        map((apiResponse: HttpResponse<any>) => {
          if (apiResponse === null) {
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

export const PARAMETER = 'params';
export const RESPONSETYPE = 'responseType';

@Injectable({
  providedIn: 'root'
})

export class FileService<T = any> implements ApiServicePrefix {
  public servicePrefix: string = 'media_file';

  constructor(private api: ApiCallService) {
  }

  /**
   * Get all files as a list from database (GridFS)
   * @param metadata part of (GridFS) instance
   * @param options HttpParams
   */
  public getAllFilesList(metadata: FileMetadata, ...options): Observable<APIGetMultiResponse<T>> {
    let params: HttpParams = new HttpParams();
    for (const option of options) {
      for (const key of Object.keys(option)) {
        params = params.append(key, option[key]);
      }
    }
    params = params.append('metadata', JSON.stringify(metadata));
    const httpOptions = httpObserveOptions;
    httpOptions[PARAMETER] = params;
    return this.api.callGet<Array<T>>(this.servicePrefix + '/', httpOptions).pipe(
      map((apiResponse: HttpResponse<APIGetMultiResponse<T>>) => {
        return apiResponse.body;
      })
    );
  }

  /**
   * Add a new file into the database (GridFS)
   * @param file raw instance
   * @param metadata part of (GridFS) instance
   */
  public postFile(file: File, metadata: FileMetadata): Observable<T> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('metadata', JSON.stringify(metadata));
    const httpOptions = httpFileOptions;
    httpOptions[RESPONSETYPE] = 'json';
    return this.api.callPost<any>(`${ this.servicePrefix }/`, formData, httpOptions).pipe(
      map((apiResponse: HttpResponse<any>) => {
        if (apiResponse.status === 204) {
          return [];
        }
        return apiResponse.body.raw;
      })
    );
  }

  /**
   * Update file into the database (GridFS)
   * @param file part of (GridFS) instance
   * @param hasReference set only reference to CmdbObject
   */
  public putFile(file: FileElement, hasReference: boolean  = false): Observable<T> {
    let params: HttpParams = new HttpParams();
    params = params.append('attachment', JSON.stringify({reference: hasReference}));
    const httpOptions = httpObserveOptions;
    httpOptions[PARAMETER] = params;
    return this.api.callPut<number>(this.servicePrefix + '/', JSON.stringify(file), httpOptions).pipe(
      map((apiResponse: HttpResponse<T>) => {
        return apiResponse.body;
      })
    );
  }


  /**
   * Download a file by name
   * @param filename name of the file
   * @param metadata part of (GridFS) instance
   */
  public downloadFile(filename: string, metadata) {
    let params: HttpParams = new HttpParams();
    params = params.append('metadata', JSON.stringify(metadata));
    const observeOptions = {
      headers: new HttpHeaders({
        'Content-Type': 'application/json'
      }),
      params: {},
      observe: resp
    };
    observeOptions[PARAMETER] = params;
    observeOptions[RESPONSETYPE] = 'blob';
    return this.api.callGet(this.servicePrefix + '/download/' + filename, observeOptions);
  }

  /**
   * Get a list of files by a regex requirement
   * Works with name
   * @param regex parameter
   */
  public getFilesListByRegex(regex: string): Observable<T[]> {
    regex = ValidatorService.validateRegex(regex).trim();
    return this.api.callGet<T[]>(this.servicePrefix + '/download/' + encodeURIComponent(regex)).pipe(
      map((apiResponse: HttpResponse<T[]>) => {
        if (apiResponse.status === 204) {
          return [];
        }
        return apiResponse.body;
      })
    );
  }


  /**
   * Delete a existing files
   * @param fileID the file id
   * @param metadata part of (GridFS) instance
   */
  public deleteFile(fileID: number, metadata): Observable<any> {
    httpFileOptions[PARAMETER] = {metadata : JSON.stringify(metadata)};
    return this.api.callDelete<any>(this.servicePrefix + '/' + fileID, httpFileOptions).pipe(
      map((apiResponse: HttpResponse<any>) => {
        return apiResponse.body;
      })
    );
  }

  /**
   * Validation: Check folder name for uniqueness
   *  @param filename must be unique
   *  @param metadata part of (GridFS) instance
   */
  public getFileElement(filename: string, metadata: FileMetadata): Observable<T> {
    httpObserveOptions[PARAMETER] = {metadata : JSON.stringify(metadata)};
    return this.api.callGet<T>(`${ this.servicePrefix }/${ filename }`, httpObserveOptions).pipe(
      map((apiResponse: HttpResponse<APIGetSingleResponse<T>>) => {
        if (apiResponse.body.result === null) {
          return null;
        }
        return apiResponse.body.result as T;
      })
    );
  }

  /**
   * This function provides building  file and directory paths.
   * @param publicID from the selected file
   * @param path separator
   * @param tree of all folder files
   */
  public pathBuilder(publicID: number, path: string[], tree: FileElement[]) {
    const temp = tree.find(f => f.public_id === publicID);
    const checker = temp ? temp.filename : '';
    path.push(checker);
    if (temp && temp.metadata && temp.metadata.parent) {
      return this.pathBuilder(temp.metadata.parent, path, tree);
    }
    return path.reverse();
  }
}
