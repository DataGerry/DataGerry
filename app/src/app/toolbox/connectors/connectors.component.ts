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
import { Component, OnInit } from '@angular/core';
import { ConnectorsService } from './services/connectors.service';

@Component({
  selector: 'app-connectors',
  templateUrl: './connectors.component.html',
  styleUrls: ['./connectors.component.scss']
})
export class ConnectorsComponent implements OnInit {
  public testResults: any = null;
  public loading: boolean = false;
  public error: string = '';
  
  // JSON data for testing
  public connectorId: number = 0;
  public connectorJson: string = `{
  "title": "testCon",
  "description": "testCon desc",
  "invoker": {
    "name": ""
  },
  "sslCert": false,
  "requestData": {
    "url": "",
    "apikey": "",
    "username": "",
    "password": ""
  },
  "timeout": 1000
}`;
  
  public testJson: string = `{
    "title": "test ",
    "description": "",
    "invoker": {
        "name": ""
    },
    "sslCert": false,
    "timeout": 1000,
    "requestData": {
        "url": "",
        "apikey": "",
        "username": "",
        "password": ""
    }
}`;

  constructor(private connectorsService: ConnectorsService) { }

  ngOnInit(): void {
  }

  /**
   * Test GET /open_celium/connectors
   */
  testGetAllConnectors(): void {
    this.loading = true;
    this.error = '';
    this.connectorsService.getAllConnectors().subscribe({
      next: (result) => {
        this.testResults = result;
        this.loading = false;
      },
      error: (err) => {
        this.error = this.formatError(err);
        this.testResults = err;
        this.loading = false;
      }
    });
  }

  /**
   * Test GET /open_celium/invokers
   */
  testGetAllInvokers(): void {
    this.loading = true;
    this.error = '';
    this.connectorsService.getAllInvokers().subscribe({
      next: (result) => {
        this.testResults = result;
        this.loading = false;
      },
      error: (err) => {
        this.error = this.formatError(err);
        this.testResults = err;
        this.loading = false;
      }
    });
  }

  /**
   * Test POST /open_celium/connectors/check
   */
  testConnectorCredentials(): void {
    try {
      const testData = JSON.parse(this.testJson);
      this.loading = true;
      this.error = '';
      this.connectorsService.testConnectorCredentials(testData).subscribe({
        next: (result) => {
          this.testResults = result;
          this.loading = false;
        },
        error: (err) => {
          this.error = this.formatError(err);
          this.testResults = err;
          this.loading = false;
        }
      });
    } catch (parseError) {
      this.error = 'Invalid JSON in test data: ' + parseError;
      this.loading = false;
    }
  }

  /**
   * Test POST /open_celium/connectors
   */
  testCreateConnector(): void {
    try {
      const connectorData = JSON.parse(this.connectorJson);
      this.loading = true;
      this.error = '';
      this.connectorsService.createConnector(connectorData).subscribe({
        next: (result) => {
          this.testResults = result;
          this.loading = false;
        },
        error: (err) => {
          this.error = this.formatError(err);
          this.testResults = err;
          this.loading = false;
        }
      });
    } catch (parseError) {
      this.error = 'Invalid JSON in connector data: ' + parseError;
      this.loading = false;
    }
  }

  /**
   * Test PUT /open_celium/connectors/{connectorId}
   */
  testUpdateConnector(): void {
    try {
      const connectorData = JSON.parse(this.connectorJson);
      this.loading = true;
      this.error = '';
      this.connectorsService.updateConnector(this.connectorId, connectorData).subscribe({
        next: (result) => {
          this.testResults = result;
          this.loading = false;
        },
        error: (err) => {
          this.error = this.formatError(err);
          this.testResults = err;
          this.loading = false;
        }
      });
    } catch (parseError) {
      this.error = 'Invalid JSON in connector data: ' + parseError;
      this.loading = false;
    }
  }

  /**
   * Test DELETE /open_celium/connectors/{connectorId}
   */
  testDeleteConnector(): void {
    this.loading = true;
    this.error = '';
    this.connectorsService.deleteConnector(this.connectorId).subscribe({
      next: (result) => {
        this.testResults = result;
        this.loading = false;
      },
      error: (err) => {
        this.error = this.formatError(err);
        this.testResults = err;
        this.loading = false;
      }
    });
  }

  /**
   * Format error for display
   */
  private formatError(error: any): string {
    if (error.error && error.error.message) {
      return error.error.message;
    }
    if (error.message) {
      return error.message;
    }
    return 'An error occurred';
  }

  /**
   * Clear results
   */
  clearResults(): void {
    this.testResults = null;
    this.error = '';
  }
}
