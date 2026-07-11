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
import { TestBed, fakeAsync, flushMicrotasks } from '@angular/core/testing';
import { HttpBackend, provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { environment } from 'src/environments/environment';
import { ConnectionService } from './connection.service';
import { RuntimeConfigService } from './runtime-config.service';

/* ------------------------------------------------------------------------------------------------------------------ */

/** Minimal stand-in for RuntimeConfigService whose merged values the tests can drive directly. */
class FakeRuntimeConfig {
  protocol = 'http';
  apiUrl = '';
  apiPort = 0;
  hasConnectionOverride = false;
}

const ORIGINAL_ENV = {
  cloudMode: environment.cloudMode,
  protocol: environment.protocol,
  apiUrl: environment.apiUrl,
  apiPort: environment.apiPort
};

describe('ConnectionService', () => {
  let httpMock: HttpTestingController;
  let backend: HttpBackend;
  let fakeRC: FakeRuntimeConfig;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting()
      ]
    });

    httpMock = TestBed.inject(HttpTestingController);
    backend = TestBed.inject(HttpBackend);
    fakeRC = new FakeRuntimeConfig();

    localStorage.removeItem('connection');

    // Neutral environment by default; individual tests set what they need.
    environment.cloudMode = false;
    environment.protocol = 'http';
    environment.apiUrl = '';
    environment.apiPort = 0;
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

  function createService(): ConnectionService {
    return new ConnectionService(backend, fakeRC as unknown as RuntimeConfigService);
  }

  /** Every constructor path sets a connection and fires one validation GET; flush it. */
  function flushValidate(base: string, ok = true): void {
    const req = httpMock.expectOne(`${base}/rest/`);
    if (ok) {
      req.flush({});
    } else {
      req.error(new ProgressEvent('error'));
    }
  }

  /* ------------------------------------------------------ CLOUD MODE ------------------------------------------------ */

  describe('cloud mode', () => {
    it('builds the connection from environment and ignores the runtime config', () => {
      environment.cloudMode = true;
      environment.protocol = 'https';
      environment.apiUrl = 'cloud.host';
      environment.apiPort = 4000;
      // Would win in non-cloud mode – must be ignored here.
      fakeRC.hasConnectionOverride = true;
      fakeRC.protocol = 'http';
      fakeRC.apiUrl = 'should-be-ignored';
      fakeRC.apiPort = 1;

      const service = createService();

      expect(service.currentConnection).toBe('https://cloud.host:4000');
      flushValidate('https://cloud.host:4000');
    });

    it('keeps the connection when validation fails', fakeAsync(() => {
      environment.cloudMode = true;
      environment.protocol = 'http';
      environment.apiUrl = 'cloud.host';
      environment.apiPort = 4000;

      const service = createService();
      flushValidate('http://cloud.host:4000', false);
      flushMicrotasks();

      expect(service.currentConnection).toBe('http://cloud.host:4000');
      expect(service.status).toBeFalse();
    }));
  });

  /* --------------------------------------------- NON-CLOUD PRECEDENCE ---------------------------------------------- */

  describe('non-cloud precedence', () => {
    it('app-config.json override wins over a cached localStorage value', () => {
      localStorage.setItem('connection', JSON.stringify('http://stored:1'));
      fakeRC.hasConnectionOverride = true;
      fakeRC.protocol = 'https';
      fakeRC.apiUrl = 'cfg.host';
      fakeRC.apiPort = 4000;

      const service = createService();

      expect(service.currentConnection).toBe('https://cfg.host:4000');
      flushValidate('https://cfg.host:4000');
    });

    it('does not persist the app-config.json override to localStorage', () => {
      fakeRC.hasConnectionOverride = true;
      fakeRC.protocol = 'http';
      fakeRC.apiUrl = 'cfg.host';
      fakeRC.apiPort = 0; // no explicit port

      const service = createService();

      expect(service.currentConnection).toBe('http://cfg.host');
      expect(localStorage.getItem('connection')).toBeNull();
      flushValidate('http://cfg.host');
    });

    it('uses the stored connection when there is no override', () => {
      localStorage.setItem('connection', JSON.stringify('http://stored:2050'));

      const service = createService();

      expect(service.currentConnection).toBe('http://stored:2050');
      flushValidate('http://stored:2050');
    });

    it('treats the literal "null" stored value as empty', () => {
      localStorage.setItem('connection', '"null"');
      environment.protocol = 'http';
      environment.apiUrl = 'env-host';
      environment.apiPort = 8000;

      const service = createService();

      expect(service.currentConnection).toBe('http://env-host:8000');
      flushValidate('http://env-host:8000');
    });

    it('falls back to the environment values when nothing is stored', () => {
      environment.protocol = 'https';
      environment.apiUrl = 'env-host';
      environment.apiPort = 4000;

      const service = createService();

      expect(service.currentConnection).toBe('https://env-host:4000');
      flushValidate('https://env-host:4000');
    });

    it('injects a window.location default when nothing at all is configured', () => {
      const proto = window.location.protocol.replace(':', '');
      const expected = `${proto}://${window.location.hostname}:4000`;

      const service = createService();

      expect(service.currentConnection).toBe(expected);
      expect(JSON.parse(localStorage.getItem('connection') as string)).toBe(expected);
      flushValidate(expected);
    });
  });

  /* ------------------------------------------------- URL CONSTRUCTION ---------------------------------------------- */

  describe('url construction', () => {
    it('omits the port segment when the port is 0', () => {
      fakeRC.hasConnectionOverride = true;
      fakeRC.protocol = 'https';
      fakeRC.apiUrl = 'no-port.host';
      fakeRC.apiPort = 0;

      const service = createService();

      expect(service.currentConnection).toBe('https://no-port.host');
      flushValidate('https://no-port.host');
    });

    it('includes the port segment when a port is set', () => {
      fakeRC.hasConnectionOverride = true;
      fakeRC.protocol = 'http';
      fakeRC.apiUrl = 'with-port.host';
      fakeRC.apiPort = 8080;

      const service = createService();

      expect(service.currentConnection).toBe('http://with-port.host:8080');
      flushValidate('http://with-port.host:8080');
    });
  });

  /* --------------------------------------------------- VALIDATION -------------------------------------------------- */

  describe('validation', () => {
    it('marks the status active after a successful validation', fakeAsync(() => {
      fakeRC.hasConnectionOverride = true;
      fakeRC.protocol = 'http';
      fakeRC.apiUrl = 'ok.host';
      fakeRC.apiPort = 4000;

      const service = createService();
      flushValidate('http://ok.host:4000', true);
      flushMicrotasks();

      expect(service.status).toBeTrue();
      expect(service.currentConnection).toBe('http://ok.host:4000');
    }));

    it('clears the connection and localStorage when validation fails in non-cloud mode', fakeAsync(() => {
      localStorage.setItem('connection', JSON.stringify('http://bad.host:1'));

      const service = createService();
      flushValidate('http://bad.host:1', false);
      flushMicrotasks();

      expect(service.currentConnection).toBe('');
      expect(service.status).toBeFalse();
      expect(localStorage.getItem('connection')).toBeNull();
    }));
  });

  /* --------------------------------------------------- PUBLIC API -------------------------------------------------- */

  describe('public API', () => {
    it('setConnectionURL stores, publishes and validates the new URL', fakeAsync(() => {
      localStorage.setItem('connection', JSON.stringify('http://init:1'));
      const service = createService();
      flushValidate('http://init:1');

      service.setConnectionURL('https', 'new.host', 8443);

      expect(service.currentConnection).toBe('https://new.host:8443');
      expect(JSON.parse(localStorage.getItem('connection') as string)).toBe('https://new.host:8443');

      const req = httpMock.expectOne('https://new.host:8443/rest/');
      req.flush({});
      flushMicrotasks();
      expect(service.status).toBeTrue();
    }));

    it('setConnectionURL skips validation when asked', () => {
      localStorage.setItem('connection', JSON.stringify('http://init:1'));
      const service = createService();
      flushValidate('http://init:1');

      service.setConnectionURL('http', 'h.host', 80, true);

      expect(service.currentConnection).toBe('http://h.host:80');
      httpMock.expectNone('http://h.host:80/rest/');
    });

    it('clearConnection resets url, status and storage', () => {
      localStorage.setItem('connection', JSON.stringify('http://init:1'));
      const service = createService();
      flushValidate('http://init:1');

      service.clearConnection();

      expect(service.currentConnection).toBe('');
      expect(service.status).toBeFalse();
      expect(localStorage.getItem('connection')).toBeNull();
    });

    it('getApiBaseUrl returns the current connection, or empty when none', () => {
      localStorage.setItem('connection', JSON.stringify('http://init:1'));
      const service = createService();
      flushValidate('http://init:1');

      expect(service.getApiBaseUrl()).toBe('http://init:1');

      service.clearConnection();
      expect(service.getApiBaseUrl()).toBe('');
    });

    it('testCustomURL GETs {base}/rest/ and resolves with the response', async () => {
      localStorage.setItem('connection', JSON.stringify('http://init:1'));
      const service = createService();
      flushValidate('http://init:1');

      const promise = service.testCustomURL('https', 'custom.host', 4000);
      const req = httpMock.expectOne('https://custom.host:4000/rest/');
      expect(req.request.method).toBe('GET');
      req.flush({ ok: true });

      await expectAsync(promise).toBeResolvedTo({ ok: true });
    });

    it('testConnection resolves true when the current connection responds', async () => {
      localStorage.setItem('connection', JSON.stringify('http://init:1'));
      const service = createService();
      flushValidate('http://init:1');

      const promise = service.testConnection();
      httpMock.expectOne('http://init:1/rest/').flush({});

      await expectAsync(promise).toBeResolvedTo(true);
    });

    it('testConnection resolves false when the current connection errors', async () => {
      localStorage.setItem('connection', JSON.stringify('http://init:1'));
      const service = createService();
      flushValidate('http://init:1');

      const promise = service.testConnection();
      httpMock.expectOne('http://init:1/rest/').error(new ProgressEvent('error'));

      await expectAsync(promise).toBeResolvedTo(false);
    });

    it('connectionReady$ emits true while connected and false after clearing', () => {
      fakeRC.hasConnectionOverride = true;
      fakeRC.protocol = 'http';
      fakeRC.apiUrl = 'ready.host';
      fakeRC.apiPort = 4000;

      const service = createService();
      flushValidate('http://ready.host:4000');

      const emissions: boolean[] = [];
      const sub = service.connectionReady$.subscribe(v => emissions.push(v));
      service.clearConnection();
      sub.unsubscribe();

      expect(emissions).toEqual([true, false]);
    });
  });

  /* ---------------------------------------------- ROBUSTNESS / EDGE ------------------------------------------------ */

  describe('robustness & edge cases', () => {
    it('does not crash on corrupt localStorage and falls through to environment', () => {
      localStorage.setItem('connection', 'not-valid-json{');
      environment.protocol = 'http';
      environment.apiUrl = 'env-host';
      environment.apiPort = 8000;

      const service = createService();

      expect(service.currentConnection).toBe('http://env-host:8000');
      flushValidate('http://env-host:8000');
    });

    it('ignores a stored value that is valid JSON but not a string', () => {
      localStorage.setItem('connection', '12345');
      environment.protocol = 'http';
      environment.apiUrl = 'env-host';
      environment.apiPort = 8000;

      const service = createService();

      expect(service.currentConnection).toBe('http://env-host:8000');
      flushValidate('http://env-host:8000');
    });

    it('does not crash when localStorage.getItem throws (storage blocked)', () => {
      spyOn(Storage.prototype, 'getItem').and.throwError('storage blocked');
      environment.protocol = 'http';
      environment.apiUrl = 'env-host';
      environment.apiPort = 8000;

      const service = createService();

      expect(service.currentConnection).toBe('http://env-host:8000');
      flushValidate('http://env-host:8000');
    });

    it('does not crash when localStorage.setItem throws during local default', () => {
      spyOn(Storage.prototype, 'setItem').and.throwError('quota exceeded');
      const proto = window.location.protocol.replace(':', '');
      const expected = `${proto}://${window.location.hostname}:4000`;

      const service = createService();

      expect(service.currentConnection).toBe(expected);
      flushValidate(expected);
    });

    it('clears the injected local default when its validation fails', fakeAsync(() => {
      const proto = window.location.protocol.replace(':', '');
      const expected = `${proto}://${window.location.hostname}:4000`;

      const service = createService();
      flushValidate(expected, false);
      flushMicrotasks();

      expect(service.currentConnection).toBe('');
      expect(localStorage.getItem('connection')).toBeNull();
    }));

    it('cloud mode marks the status active on successful validation', fakeAsync(() => {
      environment.cloudMode = true;
      environment.protocol = 'https';
      environment.apiUrl = 'cloud.host';
      environment.apiPort = 4000;

      const service = createService();
      flushValidate('https://cloud.host:4000', true);
      flushMicrotasks();

      expect(service.status).toBeTrue();
    }));

    it('cloud mode omits the port when it is 0', () => {
      environment.cloudMode = true;
      environment.protocol = 'https';
      environment.apiUrl = 'cloud.host';
      environment.apiPort = 0;

      const service = createService();

      expect(service.currentConnection).toBe('https://cloud.host');
      flushValidate('https://cloud.host');
    });

    it('setConnectionURL strips a scheme accidentally typed into the host', () => {
      localStorage.setItem('connection', JSON.stringify('http://init:1'));
      const service = createService();
      flushValidate('http://init:1');

      service.setConnectionURL('https', 'https://typed.host', 8443, true);

      expect(service.currentConnection).toBe('https://typed.host:8443');
    });

    it('setConnectionURL omits the port when it is 0', () => {
      localStorage.setItem('connection', JSON.stringify('http://init:1'));
      const service = createService();
      flushValidate('http://init:1');

      service.setConnectionURL('https', 'no-port.host', 0, true);

      expect(service.currentConnection).toBe('https://no-port.host');
    });

    it('testCustomURL rejects when the endpoint errors', async () => {
      localStorage.setItem('connection', JSON.stringify('http://init:1'));
      const service = createService();
      flushValidate('http://init:1');

      const promise = service.testCustomURL('https', 'custom.host', 4000);
      httpMock.expectOne('https://custom.host:4000/rest/').error(new ProgressEvent('error'));

      await expectAsync(promise).toBeRejected();
    });

    it('connectionReady$ does not re-emit for repeated non-empty connections', () => {
      localStorage.setItem('connection', JSON.stringify('http://init:1'));
      const service = createService();
      flushValidate('http://init:1');

      const emissions: boolean[] = [];
      const sub = service.connectionReady$.subscribe(v => emissions.push(v));
      service.setConnectionURL('http', 'another.host', 80, true); // still non-empty → suppressed
      service.clearConnection();                                  // empty → emits false
      sub.unsubscribe();

      expect(emissions).toEqual([true, false]);
    });
  });

  /* --------------------------------------- ADDITIONAL REALISTIC SCENARIOS ------------------------------------------ */

  describe('additional realistic scenarios', () => {
    // ---- stored value shapes ----
    it('uses an https stored connection with a port', () => {
      localStorage.setItem('connection', JSON.stringify('https://secure.host:443'));
      const service = createService();
      expect(service.currentConnection).toBe('https://secure.host:443');
      flushValidate('https://secure.host:443');
    });

    it('uses a stored connection without a port', () => {
      localStorage.setItem('connection', JSON.stringify('http://plain.host'));
      const service = createService();
      expect(service.currentConnection).toBe('http://plain.host');
      flushValidate('http://plain.host');
    });

    it('treats an empty-string stored value as no connection', () => {
      localStorage.setItem('connection', JSON.stringify(''));
      environment.protocol = 'http';
      environment.apiUrl = 'env-host';
      environment.apiPort = 8000;
      const service = createService();
      expect(service.currentConnection).toBe('http://env-host:8000');
      flushValidate('http://env-host:8000');
    });

    it('treats a JSON null stored value as no connection', () => {
      localStorage.setItem('connection', 'null');
      environment.protocol = 'http';
      environment.apiUrl = 'env-host';
      environment.apiPort = 8000;
      const service = createService();
      expect(service.currentConnection).toBe('http://env-host:8000');
      flushValidate('http://env-host:8000');
    });

    it('treats a JSON object stored value as no connection', () => {
      localStorage.setItem('connection', '{"host":"x"}');
      environment.protocol = 'http';
      environment.apiUrl = 'env-host';
      environment.apiPort = 8000;
      const service = createService();
      expect(service.currentConnection).toBe('http://env-host:8000');
      flushValidate('http://env-host:8000');
    });

    // ---- override host cleanup ----
    it('strips a scheme left in the config override host', () => {
      fakeRC.hasConnectionOverride = true;
      fakeRC.protocol = 'https';
      fakeRC.apiUrl = 'http://cfg.host';
      fakeRC.apiPort = 8080;
      const service = createService();
      expect(service.currentConnection).toBe('https://cfg.host:8080');
      flushValidate('https://cfg.host:8080');
    });

    it('builds an https override without a port', () => {
      fakeRC.hasConnectionOverride = true;
      fakeRC.protocol = 'https';
      fakeRC.apiUrl = 'cfg.host';
      fakeRC.apiPort = 0;
      const service = createService();
      expect(service.currentConnection).toBe('https://cfg.host');
      flushValidate('https://cfg.host');
    });

    // ---- validation across paths ----
    it('marks status active when a stored connection validates', fakeAsync(() => {
      localStorage.setItem('connection', JSON.stringify('http://stored:2050'));
      const service = createService();
      flushValidate('http://stored:2050', true);
      flushMicrotasks();
      expect(service.status).toBeTrue();
    }));

    it('keeps a config override even when validation fails, and never uses localStorage', fakeAsync(() => {
      localStorage.setItem('connection', JSON.stringify('http://old.stored:1'));
      fakeRC.hasConnectionOverride = true;
      fakeRC.protocol = 'https';
      fakeRC.apiUrl = 'unreachable.host';
      fakeRC.apiPort = 4000;
      const service = createService();
      flushValidate('https://unreachable.host:4000', false);
      flushMicrotasks();
      // The operator's explicit choice is kept; it never falls back to the stored value.
      expect(service.currentConnection).toBe('https://unreachable.host:4000');
      expect(service.status).toBeFalse();
    }));

    it('clears when the environment fallback fails validation', fakeAsync(() => {
      environment.protocol = 'http';
      environment.apiUrl = 'env-host';
      environment.apiPort = 9000;
      const service = createService();
      flushValidate('http://env-host:9000', false);
      flushMicrotasks();
      expect(service.currentConnection).toBe('');
    }));

    // ---- cloud specifics ----
    it('cloud mode ignores any stored localStorage connection', () => {
      localStorage.setItem('connection', JSON.stringify('http://stored.ignored:1'));
      environment.cloudMode = true;
      environment.protocol = 'https';
      environment.apiUrl = 'cloud.host';
      environment.apiPort = 4000;
      const service = createService();
      expect(service.currentConnection).toBe('https://cloud.host:4000');
      flushValidate('https://cloud.host:4000');
    });

    it('cloud mode strips a scheme left in environment.apiUrl', () => {
      environment.cloudMode = true;
      environment.protocol = 'https';
      environment.apiUrl = 'https://cloud.host';
      environment.apiPort = 4000;
      const service = createService();
      expect(service.currentConnection).toBe('https://cloud.host:4000');
      flushValidate('https://cloud.host:4000');
    });

    // ---- storage write failures ----
    it('clearConnection does not crash when removeItem throws', () => {
      localStorage.setItem('connection', JSON.stringify('http://init:1'));
      const service = createService();
      flushValidate('http://init:1');
      spyOn(Storage.prototype, 'removeItem').and.throwError('storage blocked');

      expect(() => service.clearConnection()).not.toThrow();
      expect(service.currentConnection).toBe('');
    });

    it('setConnectionURL updates the connection even when setItem throws', () => {
      localStorage.setItem('connection', JSON.stringify('http://init:1'));
      const service = createService();
      flushValidate('http://init:1');
      spyOn(Storage.prototype, 'setItem').and.throwError('quota exceeded');

      service.setConnectionURL('https', 'new.host', 443, true);
      expect(service.currentConnection).toBe('https://new.host:443');
    });

    // ---- API surface ----
    it('getApiBaseUrl composes into a full REST url', () => {
      localStorage.setItem('connection', JSON.stringify('https://cmdb.host:4000'));
      const service = createService();
      flushValidate('https://cmdb.host:4000');
      expect(`${service.getApiBaseUrl()}/rest`).toBe('https://cmdb.host:4000/rest');
    });

    it('applies the last setConnectionURL when called several times', () => {
      localStorage.setItem('connection', JSON.stringify('http://init:1'));
      const service = createService();
      flushValidate('http://init:1');
      service.setConnectionURL('http', 'first.host', 1, true);
      service.setConnectionURL('https', 'second.host', 2, true);
      expect(service.currentConnection).toBe('https://second.host:2');
    });

    it('testConnection resolves false after the connection was cleared', async () => {
      localStorage.setItem('connection', JSON.stringify('http://init:1'));
      const service = createService();
      flushValidate('http://init:1');
      service.clearConnection();

      const promise = service.testConnection();
      httpMock.expectOne('/rest/').error(new ProgressEvent('error'));
      await expectAsync(promise).toBeResolvedTo(false);
    });

    it('connectionReady$ emits again after clear then reconnect', () => {
      localStorage.setItem('connection', JSON.stringify('http://init:1'));
      const service = createService();
      flushValidate('http://init:1');

      const emissions: boolean[] = [];
      const sub = service.connectionReady$.subscribe(v => emissions.push(v));
      service.clearConnection();
      service.setConnectionURL('http', 'back.host', 80, true);
      sub.unsubscribe();

      expect(emissions).toEqual([true, false, true]);
    });

    it('status is false immediately after construction, before validation resolves', () => {
      localStorage.setItem('connection', JSON.stringify('http://init:1'));
      const service = createService();
      expect(service.status).toBeFalse();
      flushValidate('http://init:1');
    });
  });
});
