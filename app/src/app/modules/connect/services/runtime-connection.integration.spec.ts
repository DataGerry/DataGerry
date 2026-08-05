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
import { TestBed } from '@angular/core/testing';
import { HttpBackend, provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { environment } from 'src/environments/environment';
import { ConnectionService } from './connection.service';
import { RuntimeConfigService } from './runtime-config.service';

/* ------------------------------------------------------------------------------------------------------------------ */
/*
 * INTEGRATION: RuntimeConfigService (real) → ConnectionService (real).
 *
 * The two unit specs each isolate one service (ConnectionService uses a fake runtime config). This
 * spec wires the REAL services together the way the app does at runtime: an APP_INITIALIZER calls
 * runtimeConfig.load() BEFORE bootstrap, then ConnectionService — constructed later — reads the
 * already-loaded values. The `/rest/frontend_init` HTTP response is mocked to stand in for the
 * backend route, so this proves the full "backend JSON → applied REST connection" path without a network.
 */

const ORIGINAL_ENV = {
  cloudMode: environment.cloudMode,
  protocol: environment.protocol,
  apiUrl: environment.apiUrl,
  apiPort: environment.apiPort
};

describe('RuntimeConfig → Connection (integration)', () => {
  let httpMock: HttpTestingController;
  let backend: HttpBackend;
  let runtimeConfig: RuntimeConfigService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        RuntimeConfigService,
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting()
      ]
    });

    httpMock = TestBed.inject(HttpTestingController);
    backend = TestBed.inject(HttpBackend);
    runtimeConfig = TestBed.inject(RuntimeConfigService);

    localStorage.removeItem('connection');

    // Distinctive environment defaults so "fell back to environment" is unambiguous.
    environment.cloudMode = false;
    environment.protocol = 'http';
    environment.apiUrl = 'env-host';
    environment.apiPort = 9999;
  });

  afterEach(() => {
    httpMock.verify();
    try {
      localStorage.removeItem('connection');
    } catch {
      // A storage spy from the test may still be throwing during teardown.
    }
    environment.cloudMode = ORIGINAL_ENV.cloudMode;
    environment.protocol = ORIGINAL_ENV.protocol;
    environment.apiUrl = ORIGINAL_ENV.apiUrl;
    environment.apiPort = ORIGINAL_ENV.apiPort;
  });

  /* ------------------------------------------------------ HELPERS -------------------------------------------------- */

  /** Drives runtimeConfig.load() and flushes the mocked backend body for /rest/frontend_init. */
  async function loadBackendBody(body: unknown): Promise<void> {
    const pending = runtimeConfig.load();
    const req = httpMock.expectOne(r => r.url.startsWith('rest/frontend_init'));
    req.flush(body);
    await pending;
  }

  /** Drives runtimeConfig.load() and answers the /rest/frontend_init request with an HTTP error. */
  async function loadBackendError(status: number): Promise<void> {
    const pending = runtimeConfig.load();
    const req = httpMock.expectOne(r => r.url.startsWith('rest/frontend_init'));
    req.flush('error', { status, statusText: 'Error' });
    await pending;
  }

  /** Builds the real ConnectionService AFTER the runtime config has loaded (mirrors bootstrap order). */
  function connect(): ConnectionService {
    return new ConnectionService(backend, runtimeConfig);
  }

  /** Satisfies the single validation GET fired by the ConnectionService constructor. */
  function flushValidate(base: string, ok = true): void {
    const req = httpMock.expectOne(`${base}/rest/`);
    if (ok) {
      req.flush({});
    } else {
      req.error(new ProgressEvent('error'));
    }
  }

  /** Flushes validation and lets the awaited status promise settle. */
  async function flushValidateAndSettle(base: string, ok = true): Promise<void> {
    flushValidate(base, ok);
    await Promise.resolve();
    await Promise.resolve();
  }

  /* -------------------------------------------- BOOTSTRAP REQUEST SHAPE -------------------------------------------- */

  describe('bootstrap request', () => {
    it('fetches /rest/frontend_init as a relative, same-origin URL (no host/scheme)', async () => {
      const pending = runtimeConfig.load();
      const req = httpMock.expectOne(r => r.url.startsWith('rest/frontend_init'));

      // Relative URL → the browser resolves it against the page origin. This is why fetching the
      // connection config needs no connection config (no bootstrap paradox).
      expect(req.request.url).not.toContain('://');
      expect(req.request.method).toBe('GET');

      req.flush({});
      await pending;

      const service = connect();
      flushValidate('http://env-host:9999');
      expect(service).toBeTruthy();
    });
  });

  /* --------------------------------------- COMPLETE BACKEND CONFIG (LOCKED) ---------------------------------------- */

  describe('complete backend config becomes the locked connection', () => {
    it('applies protocol/host/port from the backend file', async () => {
      await loadBackendBody({ protocol: 'https', apiUrl: 'cmdb.example.com', apiPort: 4000 });

      const service = connect();

      expect(service.currentConnection).toBe('https://cmdb.example.com:4000');
      flushValidate('https://cmdb.example.com:4000');
    });

    it('applies the real deployment file shape (numeric-string port)', async () => {
      // The exact shape an operator writes into etc/app-config.json.
      await loadBackendBody({ protocol: 'http', apiUrl: '192.168.64.2', apiPort: '2120' });

      const service = connect();

      expect(service.currentConnection).toBe('http://192.168.64.2:2120');
      flushValidate('http://192.168.64.2:2120');
    });

    it('drops the port segment when the backend supplies port 0', async () => {
      await loadBackendBody({ protocol: 'https', apiUrl: 'cmdb.company.com', apiPort: 0 });

      const service = connect();

      expect(service.currentConnection).toBe('https://cmdb.company.com');
      flushValidate('https://cmdb.company.com');
    });

    it('never persists the backend-driven connection to localStorage', async () => {
      await loadBackendBody({ protocol: 'http', apiUrl: 'cfg.host', apiPort: 4000 });

      const service = connect();

      expect(service.currentConnection).toBe('http://cfg.host:4000');
      expect(localStorage.getItem('connection')).toBeNull();
      flushValidate('http://cfg.host:4000');
    });

    it('wins over a previously stored connection', async () => {
      localStorage.setItem('connection', JSON.stringify('http://stored.host:1'));
      await loadBackendBody({ protocol: 'https', apiUrl: 'cfg.host', apiPort: 8443 });

      const service = connect();

      expect(service.currentConnection).toBe('https://cfg.host:8443');
      flushValidate('https://cfg.host:8443');
    });

    it('is kept even when unreachable, and does not fall back to storage', async () => {
      localStorage.setItem('connection', JSON.stringify('http://stored.host:1'));
      await loadBackendBody({ protocol: 'http', apiUrl: 'down.host', apiPort: 2120 });

      const service = connect();
      await flushValidateAndSettle('http://down.host:2120', false);

      expect(service.currentConnection).toBe('http://down.host:2120');
      expect(service.status).toBeFalse();
    });

    it('marks the status active once the backend connection validates', async () => {
      await loadBackendBody({ protocol: 'http', apiUrl: 'up.host', apiPort: 2120 });

      const service = connect();
      await flushValidateAndSettle('http://up.host:2120', true);

      expect(service.status).toBeTrue();
      expect(service.currentConnection).toBe('http://up.host:2120');
    });
  });

  /* -------------------------------------- INCOMPLETE / IGNORED BACKEND CONFIG -------------------------------------- */

  describe('incomplete backend config falls through to the normal precedence', () => {
    it('ignores a host-only file and uses the environment default', async () => {
      await loadBackendBody({ apiUrl: 'partial.host' });

      const service = connect();

      expect(service.currentConnection).toBe('http://env-host:9999');
      flushValidate('http://env-host:9999');
    });

    it('ignores a file missing the port and uses a stored connection when present', async () => {
      localStorage.setItem('connection', JSON.stringify('http://stored.host:2050'));
      await loadBackendBody({ protocol: 'https', apiUrl: 'partial.host' });

      const service = connect();

      expect(service.currentConnection).toBe('http://stored.host:2050');
      flushValidate('http://stored.host:2050');
    });

    it('ignores a file whose fields are invalid and get dropped', async () => {
      // Bad protocol + out-of-range port → sanitized away → incomplete → not an override.
      await loadBackendBody({ protocol: 'ftp', apiUrl: 'good.host', apiPort: 999999 });

      const service = connect();

      expect(service.currentConnection).toBe('http://env-host:9999');
      flushValidate('http://env-host:9999');
    });
  });

  /* --------------------------------- MISSING / BROKEN BACKEND (the debugging saga) --------------------------------- */

  describe('missing or broken backend response', () => {
    it('empty {} (server fallback when no file on disk) → environment default', async () => {
      await loadBackendBody({});

      const service = connect();

      expect(service.currentConnection).toBe('http://env-host:9999');
      flushValidate('http://env-host:9999');
    });

    it('HTTP 404 (route unreachable) → environment default', async () => {
      await loadBackendError(404);

      const service = connect();

      expect(service.currentConnection).toBe('http://env-host:9999');
      flushValidate('http://env-host:9999');
    });

    it('non-JSON body (SPA placeholder HTML) → treated as no override → environment default', async () => {
      // Exactly the failure mode from the routing bug: the 404 fallback served index.html with a 200.
      // sanitize() rejects the non-object body, so the connection degrades safely instead of breaking.
      await loadBackendBody('<!doctype html><title>PLACEHOLDER FOR DATAGERRY APP</title>');

      const service = connect();

      expect(service.currentConnection).toBe('http://env-host:9999');
      flushValidate('http://env-host:9999');
    });

    it('when nothing is configured at all, injects the window.location default', async () => {
      environment.apiUrl = '';
      environment.apiPort = 0;
      await loadBackendBody({});

      const proto = window.location.protocol.replace(':', '');
      const expected = `${proto}://${window.location.hostname}:4000`;

      const service = connect();

      expect(service.currentConnection).toBe(expected);
      flushValidate(expected);
    });
  });

  /* ------------------------------------------------- CLOUD MODE ---------------------------------------------------- */

  describe('cloud mode', () => {
    it('never fetches /rest/frontend_init and builds the connection from environment.cloud', async () => {
      environment.cloudMode = true;
      environment.protocol = 'https';
      environment.apiUrl = 'cloud.host';
      environment.apiPort = 4000;

      await runtimeConfig.load();
      httpMock.expectNone(r => r.url.startsWith('rest/frontend_init'));

      const service = connect();

      expect(service.currentConnection).toBe('https://cloud.host:4000');
      flushValidate('https://cloud.host:4000');
    });
  });
});
