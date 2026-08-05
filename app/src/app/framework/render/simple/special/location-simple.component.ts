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

import { Component, OnInit } from '@angular/core';

import { LocationService } from 'src/app/framework/services/location.service';

import { RenderFieldComponent } from '../../fields/components.fields';
import { RenderResult } from '../../../models/cmdb-render';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-location-simple',
    templateUrl: './location-simple.component.html',
    styleUrls: ['./location-simple.component.scss'],
    standalone: false
})
export class LocationSimpleComponent extends RenderFieldComponent implements OnInit {

  /** hold the location data if there is any */
  locationData: RenderResult;

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    constructor(private locationService: LocationService) {
      super();
    }


    public ngOnInit() {
      if(this.data.value && this.data.value > 0){
        this.getLocation(this.data.value);
      }
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                      API CALLS                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */


    /**
     * Retrieves the location of the current object
     * 
     * @param public_id public_id of the location which should be retrieved
     */
    private getLocation(public_id: number){
      this.locationService.getLocation(public_id).subscribe((response: RenderResult) => {
        this.locationData = response;
      });
    }

}
