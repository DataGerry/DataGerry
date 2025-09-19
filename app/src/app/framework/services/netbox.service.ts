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
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { environment } from '../../../environments/environment';

@Injectable({
  providedIn: 'root'
})
export class NetboxService {
  private readonly apiToken = 'f1fbeace6974dd42ff90b89231e2d4e97c4f9dc2';
  
  // Use proxy path for both development and cloud modes
  private readonly netboxBaseUrl = '/netbox';

  constructor(private http: HttpClient) { }

  /**
   * Fetches the rack elevation SVG from NetBox API
   * @param rackId The rack ID to fetch elevation for (defaults to 51)
   */
  getRackElevationSvg(rackId: number = 51): Observable<string> {
    // Add trailing slash to avoid NetBox 301 redirect
    const url = `${this.netboxBaseUrl}/api/dcim/racks/${rackId}/elevation/?render=svg`;
    
    // Debug logging to help troubleshoot
    // console.log('NetBox service called with environment:', environment);
    // console.log('Cloud mode:', environment.cloudMode);
    // console.log('Request URL:', url);
    
    // For cloud mode, we need to handle authentication directly since proxy might not be working
    let headers = new HttpHeaders();
    if (environment.cloudMode) {
      headers = headers.set('Authorization', `Token ${this.apiToken}`);
      // console.log('Adding Authorization header for cloud mode');
    } else {
      // console.log('Proxy should handle authentication in development mode');
    }

    return this.http.get(url, { 
      headers: headers,
      responseType: 'text'
    }).pipe(
      catchError(error => {
        console.error('NetBox API error:', error);
        // console.error('Error details:', error.message, error.status, error.url);
        throw error;
      })
    );
  }
}
