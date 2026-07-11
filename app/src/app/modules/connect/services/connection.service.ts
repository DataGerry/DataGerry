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
import { HttpBackend, HttpClient } from '@angular/common/http';
import { BehaviorSubject, Observable, lastValueFrom } from 'rxjs';
import { map, distinctUntilChanged } from 'rxjs/operators';
import { environment } from 'src/environments/environment';
import { RuntimeConfigService } from './runtime-config.service';

@Injectable({ providedIn: 'root' })
export class ConnectionService {
  private connection$ = new BehaviorSubject<string>('');
  private connectionStatus = false;
  // True when the connection is authoritative (cloud env, or a complete app-config.json). Such a
  // connection is the operator's explicit choice and must never be cleared or replaced on a failed
  // reachability check, nor fall back to localStorage/environment.
  private connectionLocked = false;
  private http: HttpClient;
  private readonly LOCAL_DEFAULT_PORT = 4000;

  /** Emits true once a non-empty URL is available */
  public readonly connectionReady$: Observable<boolean> =
    this.connection$.pipe(map(v => !!v), distinctUntilChanged());

  get currentConnection(): string { return this.connection$.value; }
  get status(): boolean { return this.connectionStatus; }

  constructor(backend: HttpBackend, private runtimeConfig: RuntimeConfigService) {
    this.http = new HttpClient(backend);

    if (environment.cloudMode) {
      // ─── CLOUD MODE: connection comes straight from environment.cloud.ts ──────────────────
      const url = this.buildUrl(
        environment.protocol,
        environment.apiUrl,
        environment.apiPort
      );
      this.connectionLocked = true;
      this.connection$.next(url);
      this.validateAsync();
      return;
    }

    // ─── NON-CLOUD MODE ──────────────────────────────────────────────
    // Precedence: runtime app-config.json → stored/manual connection → environment → local default.

    if (this.runtimeConfig.hasConnectionOverride) {
      // A complete app-config.json is the operator's explicit, final choice: use it verbatim, never
      // fall back to localStorage/environment, and keep it even if it is unreachable. Not persisted.
      const url = this.buildUrl(
        this.runtimeConfig.protocol,
        this.runtimeConfig.apiUrl,
        this.runtimeConfig.apiPort
      );
      this.connectionLocked = true;
      this.connection$.next(url);
      this.validateAsync();
      return;
    }

    const stored = this.readStoredConnection();

    if (stored) {
      this.connection$.next(stored);
      this.validateAsync();
      return;
    }

    if (environment.apiUrl) {
      const url = this.buildUrl(
        environment.protocol,
        environment.apiUrl,
        environment.apiPort
      );
      this.connection$.next(url);
      this.validateAsync();
      return;
    }

    this.injectLocalDefault();
  }


  /**
   *  Sets the connection URL and updates the local storage.
   * @param protocol 
   * @param host 
   * @param port 
   * @param skipValidate 
   */
  public setConnectionURL(
    protocol: string,
    host: string,
    port: number,
    skipValidate = false
  ): void {
    const url = this.buildUrl(protocol, host, port);

    this.persistConnection(url);

    this.connection$.next(url);

    if (!skipValidate) {
      this.validateAsync();
    }
  }

  /**
   *  Tests a custom URL by making a GET request to the REST endpoint.
   * @param protocol 
   * @param host 
   * @param port 
   * @returns 
   */
  public async testCustomURL(
    protocol: string,
    host: string,
    port: number
  ): Promise<any> {
    const base = this.buildUrl(protocol, host, port);
    const testUrl = `${base}/rest/`;
    return lastValueFrom(this.http.get<any>(testUrl));
  }

  /** Quick boolean test of current connection */
  public async testConnection(): Promise<boolean> {
    try {
      await this.connect();
      return true;
    } catch (err) {
      return false;
    }
  }

  /**
   * Clears the current connection URL from local storage
   */
  public clearConnection(): void {
    this.removeStoredConnection();
    this.connection$.next('');
    this.connectionStatus = false;
  }

  /** For your API calls */
  public getApiBaseUrl(): string {
    const base = this.currentConnection
      ? `${this.currentConnection}`
      : '';
    return base;
  }

  // ─── PRIVATE ─────────────────────────────────────────────────────

  /**
   * Reads the persisted connection, tolerating a disabled/blocked localStorage or a corrupt
   * stored value so a bad entry can never crash startup.
   */
  private readStoredConnection(): string {
    try {
      const raw = localStorage.getItem('connection');

      if (!raw || raw === '"null"') {
        return '';
      }

      const parsed = JSON.parse(raw);
      return typeof parsed === 'string' ? parsed : '';
    } catch {
      return '';
    }
  }


  /** Persists the connection, swallowing errors from a disabled or full localStorage. */
  private persistConnection(url: string): void {
    try {
      localStorage.setItem('connection', JSON.stringify(url));
    } catch {
      // Storage unavailable (private mode / quota); the connection still works this session.
    }
  }


  /** Removes the persisted connection, tolerating a disabled localStorage. */
  private removeStoredConnection(): void {
    try {
      localStorage.removeItem('connection');
    } catch {
      // Nothing to do when storage is unavailable.
    }
  }


  /**
   * Builds a URL from the given protocol, host, and port.
   * @param protocol 
   * @param host 
   * @param port 
   * @returns 
   */
  private buildUrl(protocol: string, host: string, port: number): string {
    const h = host.replace(/^https?:\/\//, '');
    return port
      ? `${protocol}://${h}:${port}`
      : `${protocol}://${h}`;
  }


  /**
   * Injects a local default connection URL into local storage and updates the connection observable.
   */
  private injectLocalDefault(): void {
    const protocol = window.location.protocol.replace(':', '');
    const hostname = window.location.hostname;
    const port = this.LOCAL_DEFAULT_PORT;

    const url = this.buildUrl(protocol, hostname, port);

    this.persistConnection(url);
    this.connection$.next(url);

    this.validateAsync();
  }


  /**
   *  Validates the current connection asynchronously.
   * @returns Validates the current connection by attempting to connect to the REST endpoint.
   */
  private async validateAsync(): Promise<void> {
    const base = this.currentConnection;

    if (!base) {
      this.connectionStatus = false;
      return;
    }

    try {
      await this.connectTo(base);
      this.connectionStatus = true;
    } catch (err) {
      this.connectionStatus = false;
      // Locked connections (cloud env / complete app-config.json) are the operator's explicit
      // choice — keep them even when unreachable. Only auto-derived connections are cleared.
      if (!this.connectionLocked) {
        this.clearConnection();
      }
    }
  }


  /**
   *  Connects to the REST endpoint of the given base URL.
   * @param base 
   * @returns 
   */
  private connectTo(base: string) {
    const url = `${base}/rest/`;
    return lastValueFrom(this.http.get<any>(url));
  }

  /**
   *  Connects to the current connection URL.
   * @returns 
   */
  private connect() {
    return this.connectTo(this.currentConnection);
  }
}