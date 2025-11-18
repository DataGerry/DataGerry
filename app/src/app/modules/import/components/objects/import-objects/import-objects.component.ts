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
import { Component, OnDestroy, OnInit } from '@angular/core';

import { Subscription } from 'rxjs';

import { ImportService } from 'src/app/modules/import/services/import.service';
import { SidebarService } from 'src/app/layout/services/sidebar.service';

import { CmdbType } from 'src/app/framework/models/cmdb-type';
import { ImporterConfig, ImporterFile, ImportResponse } from '../../../models/import-object.models';
import { ToastService } from 'src/app/layout/toast/toast.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-import-objects',
    templateUrl: './import-objects.component.html',
    styleUrls: ['./import-objects.component.scss'],
    standalone: false
})
export class ImportObjectsComponent implements OnInit, OnDestroy {

    private fileReader: FileReader;
    public typeInstance: CmdbType = undefined;

    // Importer Data
    private importerSubscription: Subscription;
    public importerFile: ImporterFile = {} as ImporterFile;
    public importerConfig: ImporterConfig = {} as ImporterConfig;
    // at the moment only MAPPING
    public defaultImporterConfig: any;

    // Parser Data
    private parseDataSubscription: Subscription;
    public parserConfig: any = undefined;
    public parsedData: any = undefined;

    // Mapping
    public mapping: [] = undefined;

    // Import Response
    public importResponse: ImportResponse = undefined;

    /* ------------------------------------------------------------------------------------------------------------------ */
    /*                                                     LIFE CYCLE                                                     */
    /* ------------------------------------------------------------------------------------------------------------------ */

    public constructor(private importService: ImportService, public sidebarService: SidebarService, private toastService: ToastService) {
        this.fileReader = new FileReader();
        this.importerSubscription = new Subscription();
        this.parseDataSubscription = new Subscription();
    }


    public ngOnInit(): void {
        this.fileReader.onload = () => {
            this.importerFile.fileContent = this.fileReader.result;
        };
    }


    public ngOnDestroy(): void {
        if (this.fileReader.readyState !== FileReader.DONE) {
            this.fileReader.abort();
        }

        this.importerSubscription?.unsubscribe();
        this.parseDataSubscription?.unsubscribe();
    }

    /* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

    public formatChange(format: string) {
        this.importerFile.fileFormat = format;
        const defaultImporterConfig = this.importService.getObjectImporterDefaultConfig(this.importerFile.fileFormat)
            .subscribe({
                next: (defaultConfig: any) => {
                    this.defaultImporterConfig = defaultConfig;
                },
                error: (e) => this.toastService.error(e?.error?.message),
                complete: () => defaultImporterConfig.unsubscribe()
            })
    }


    public fileChange(file: File) {
        this.importerFile.file = file;
        this.importerFile.fileName = file.name;
        this.fileReader.readAsText(file);
    }


    public parserConfigChange(config: any) {
        setTimeout(() => {
            this.parserConfig = config;
        }, 0)
    }


    public importConfigChange(config: any) {
        if (config !== undefined) {
            this.importerConfig = config as ImporterConfig;

            if (this.typeInstance !== undefined) {
                this.importerConfig.type_id = this.typeInstance.public_id as number;
            }
        }
    }


    public typeChange(change: any) {
        this.importerConfig.type_id = change.typeID as number;
        this.typeInstance = change.typeInstance as CmdbType;
    }


    public mappingChange(change: any) {
        this.mapping = change.filter(value => Object.keys(value).length !== 0);
    }


    public onParseData() {
        this.parseDataSubscription = this.importService.postObjectParser(
            this.importerFile.file, this.importerFile.fileFormat, this.parserConfig).subscribe({
                next: (parsedData) => {
                    this.parsedData = parsedData;
                    // this.cdr.detectChanges();
                },
                error: (e) => this.toastService.error(e?.error?.message),
            });
    }


    public startImport() {
        const runtimeConfig = this.importerConfig;

        if (this.defaultImporterConfig.manually_mapping) {
            runtimeConfig.mapping = this.mapping;
        }

        this.importService.importObjects(this.importerFile.file, this.importerFile.fileFormat,
            this.parserConfig, runtimeConfig)
            .subscribe({
                next: (importResponse) => {
                    this.importResponse = importResponse;
                },
                error: (e) => {
                    this.toastService.error(e?.error?.message)
                },
                complete: () => {
                    this.sidebarService.updateTypeCounter(this.typeInstance.public_id);
                }
            });
    }
}
