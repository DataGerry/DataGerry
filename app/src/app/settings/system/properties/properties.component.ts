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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

import { Component, OnDestroy, OnInit } from '@angular/core';
import { SystemService } from '../system.service';
import { ReplaySubject } from 'rxjs';
import { ToastService } from '../../../layout/toast/toast.service';
import { takeUntil } from 'rxjs/operators';

@Component({
  selector: 'cmdb-properties',
  templateUrl: './properties.component.html',
  styleUrls: ['./properties.component.scss']
})
export class PropertiesComponent implements OnInit, OnDestroy {

  public config: {
    path: string,
    properties: any[]
  };

  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

  constructor(private systemService: SystemService, private toast: ToastService) {
  }

  public ngOnInit(): void {
    this.systemService.getConfigInformation()
      .pipe(takeUntil(this.subscriber))
      .subscribe({
        next: (config) => {
          this.config = {
            path: config.path,
            properties: []
          };
          for (const section of config.properties) {
            for (const prop of section[1]) {
              this.config.properties.push({
                section: section[0],
                key: prop[0],
                value: prop[1]
              });
            }
          }
        },
        error: (error) => {
          this.toast.error(error);
        }
      });
  }

  public ngOnDestroy(): void {
    this.subscriber?.next();
    this.subscriber?.complete();
  }

}
