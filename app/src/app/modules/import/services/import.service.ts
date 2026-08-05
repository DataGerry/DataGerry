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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Injectable } from '@angular/core';
import { HttpHeaders } from '@angular/common/http';

import { Observable, map } from 'rxjs';

import { ApiCallService, ApiServicePrefix } from '../../../services/api-call.service';

import { ImporterConfig } from '../models/import-object.models';
/* ------------------------------------------------------------------------------------------------------------------ */

declare type HttpObserve = 'body' | 'events' | 'response';
export const resp: HttpObserve = 'response';


export const httpImportFileOptions = {
    headers: new HttpHeaders({}),
    params: {},
    observe: resp
};

@Injectable({
     providedIn: 'root'
})
export class ImportService implements ApiServicePrefix {

    public servicePrefix: string = 'import';
    private objectPrefix: string = 'object';
    private typePrefix: string = 'type';
    private threatPrefix = 'isms/importer/threat';
    private riskPrefix = 'isms/importer/risk';
    private controlMeasurePrefix = 'isms/importer/control_measure';
    private vulnerabilityPrefix = 'isms/importer/vulnerability';


    constructor(private api: ApiCallService) {

    }

    public importThreatFile(file: File): Observable<any> {
        const formData = new FormData();
        formData.append('file', file, file.name);
        return this.api.callPost<any>(this.threatPrefix, formData, httpImportFileOptions).pipe(
            map(response => response.body)
        );
    }

    public importRiskFile(file: File): Observable<any> {
        const formData = new FormData();
        formData.append('file', file, file.name);
        return this.api.callPost<any>(this.riskPrefix, formData, httpImportFileOptions).pipe(
            map(response => response.body)
        );
    }

    public importControlMeasureFile(file: File): Observable<any> {
        const formData = new FormData();
        formData.append('file', file, file.name);
        return this.api.callPost<any>(this.controlMeasurePrefix, formData, httpImportFileOptions).pipe(
            map(response => response.body)
        );
    }

    public importVulnerabilityFile(file: File): Observable<any> {
        const formData = new FormData();
        formData.append('file', file, file.name);
        return this.api.callPost<any>(this.vulnerabilityPrefix, formData, httpImportFileOptions).pipe(
            map(response => response.body)
        );
    }


    public importObjects(file: File, fileFormat: string, parserConfig: any, importerConfig: ImporterConfig): Observable<any> {
        const formData = new FormData();
        formData.append('file', file, file.name);
        formData.append('file_format', fileFormat);
        formData.append('parser_config', JSON.stringify(parserConfig));
        formData.append('importer_config', JSON.stringify(importerConfig));

        return this.api.callPost<any>(`${ this.servicePrefix }/${ this.objectPrefix }/`, formData, httpImportFileOptions).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            })
        );
    }


    public postObjectParser(file: File, fileFormat: string, parserConfig: any): Observable<any> {
        const formData = new FormData();
        formData.append('file', file, file.name);
        formData.append('file_format', fileFormat);
        formData.append('parser_config', JSON.stringify(parserConfig));

        return this.api.callPost<any>(`${ this.servicePrefix }/${ this.objectPrefix }/parse/`, formData, httpImportFileOptions).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            })
        );
    }


    public getObjectImporterDefaultConfig(fileType: string): Observable<any> {
        return this.api.callGet<any>(`${ this.servicePrefix }/${ this.objectPrefix }/importer/config/${ fileType }/`).pipe(
            map((apiResponse) => {
                if (apiResponse.status === 204) {
                    return {};
                }

                return apiResponse.body;
            })
        );
    }


    public getObjectParserDefaultConfig(fileType: string): Observable<any> {
        return this.api.callGet<any>(`${ this.servicePrefix }/${ this.objectPrefix }/parser/default/${ fileType }/`).pipe(
            map((apiResponse) => {
                if (apiResponse.status === 204) {
                    return {};
                }

                return apiResponse.body;
            })
        );
    }


    public getObjectImporters(): Observable<string[]> {
        return this.api.callGet<string[]>(`${ this.servicePrefix }/${ this.objectPrefix }/importer/`).pipe(
            map((apiResponse) => {
                if (apiResponse.status === 204) {
                    return [];
                }

                return apiResponse.body;
            })
        );
    }


    public postUpdateTypeParser(formData: FormData): Observable<any> {
        return this.api.callPost<any>(`${ this.servicePrefix }/${ this.typePrefix }/update/`, formData, httpImportFileOptions).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            })
        );
    }


    public postCreateTypeParser(formData: FormData): Observable<any> {
        return this.api.callPost<any>(`${ this.servicePrefix }/${ this.typePrefix }/create/`, formData, httpImportFileOptions).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            })
        );
    }
}
