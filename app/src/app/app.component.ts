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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, OnDestroy, OnInit } from '@angular/core';
import { ActivatedRoute, Event, NavigationEnd, Router } from '@angular/router';

import { ReplaySubject } from 'rxjs';
/* ------------------------------------------------------------------------------------------------------------------ */

declare type AppView = 'full' | 'embedded';

@Component({
  selector: 'cmdb-root',
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.scss']
})
export class AppComponent implements OnInit, OnDestroy {

  private applicationSubscriber: ReplaySubject<void> = new ReplaySubject<void>();
  public readonly defaultView: AppView = 'full';
  public view: AppView;

  /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(private router: Router, private route: ActivatedRoute) {
        this.view = this.defaultView;
    }


    public ngOnInit(): void {
        this.router.events.subscribe((e: Event) => {
        if (e instanceof NavigationEnd) {
            this.route.url.subscribe(() => {
            if (this.route.snapshot.firstChild.data.view) {
                this.view = this.route.snapshot.firstChild.data.view;
            } else {
                this.view = this.defaultView;
            }

            });
        }
        });
    }


    public ngOnDestroy(): void {
        this.applicationSubscriber?.next();
        this.applicationSubscriber?.complete();
    }
}
