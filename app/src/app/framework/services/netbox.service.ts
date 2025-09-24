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
import { Observable, from } from 'rxjs';
import { catchError, switchMap } from 'rxjs/operators';
import { environment } from '../../../environments/environment';
import { TypeService } from './type.service';

@Injectable({
  providedIn: 'root'
})
export class NetboxService {
  private apiToken: string | null = null;
  private isInitialized = false;
  private initializationPromise: Promise<void> | null = null;
  
  // Use proxy path for both development and cloud modes
  private readonly netboxBaseUrl = '/netbox';

  constructor(private http: HttpClient, private typeService: TypeService) {}

  /**
   * Initialize the service by fetching the API token
   * This method is called lazily when needed
   */
  private initialize(): Promise<void> {
    // If already initialized, return resolved promise
    if (this.isInitialized) {
      return Promise.resolve();
    }

    // If initialization is in progress, return the existing promise
    if (this.initializationPromise) {
      return this.initializationPromise;
    }

    // Start new initialization
    this.initializationPromise = new Promise((resolve, reject) => {
      this.typeService.getTypeByName('rack').subscribe({
        next: (type) => {
          if (type && type.description) {
            this.apiToken = type.description;
            this.isInitialized = true;
            resolve();
          } else {
            const error = new Error('Rack type not found or has no description');
            reject(error);
          }
        },
        error: (err) => {
          reject(err);
        }
      });
    });

    return this.initializationPromise;
  }

  /**
   * Fetches the rack elevation SVG from NetBox API
   * @param rackId The rack ID to fetch elevation for (defaults to 51)
   */
  getRackElevationSvg(rackId: number = 51): Observable<string> {
    // Ensure service is initialized before making the API call
    return from(this.initialize()).pipe(
      switchMap(() => {
        // Add trailing slash to avoid NetBox 301 redirect
        const url = `${this.netboxBaseUrl}/api/dcim/racks/${rackId}/elevation/?render=svg`;
        
        // Debug logging to help troubleshoot
        // console.log('NetBox service called with environment:', environment);
        // console.log('Cloud mode:', environment.cloudMode);
        // console.log('Request URL:', url);
        
        // For cloud mode, we need to handle authentication directly since proxy might not be working
        let headers = new HttpHeaders();
          if (!this.apiToken) {
            throw new Error('NetBox API token is not available');
          }
          headers = headers.set('Authorization', `Token ${this.apiToken}`);
          // console.log('Adding Authorization header for cloud mode');


        return this.http.get(url, { 
          headers: headers,
          responseType: 'text'
        }).pipe(
          catchError(error => {
            // console.error('Error details:', error.message, error.status, error.url);
            throw error;
          })
        );
      }),
      catchError(initError => {
        throw new Error(`Failed to initialize NetBox service: ${initError.message}`);
      })
    );
  }

  /**
   * 
   * @returns The stored API token or null if not set
   */
  getApiToken(): string | null {
    return this.apiToken;
  }

  clearApiToken() {
    this.apiToken = null;
    this.isInitialized = false;
    this.initializationPromise = null;
  }
}
