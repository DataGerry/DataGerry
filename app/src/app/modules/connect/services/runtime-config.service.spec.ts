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
import { provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { environment } from 'src/environments/environment';
import { RuntimeConfigService, RuntimeConnectionConfig } from './runtime-config.service';

/* ------------------------------------------------------------------------------------------------------------------ */

/** True originals so every test starts from and returns to a known environment. */
const ORIGINAL_ENV = {
  cloudMode: environment.cloudMode,
  protocol: environment.protocol,
  apiUrl: environment.apiUrl,
  apiPort: environment.apiPort
};

describe('RuntimeConfigService', () => {
  let service: RuntimeConfigService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        RuntimeConfigService,
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting()
      ]
    });

    // Deterministic, distinctive environment defaults so "fall back to environment" is provable.
    environment.cloudMode = false;
    environment.protocol = 'http';
    environment.apiUrl = 'env-host';
    environment.apiPort = 9999;

    service = TestBed.inject(RuntimeConfigService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    environment.cloudMode = ORIGINAL_ENV.cloudMode;
    environment.protocol = ORIGINAL_ENV.protocol;
    environment.apiUrl = ORIGINAL_ENV.apiUrl;
    environment.apiPort = ORIGINAL_ENV.apiPort;
  });

  /** Runs load() against a mocked /rest/frontend_init response and waits for it to settle. */
  async function loadWith(body: unknown): Promise<void> {
    const pending = service.load();
    const req = httpMock.expectOne(r => r.url.startsWith('rest/frontend_init'));
    req.flush(body);
    await pending;
  }

  /* ------------------------------------------------------ CLOUD MODE ------------------------------------------------ */

  describe('cloud mode', () => {
    it('never fetches the runtime config and reports no override', async () => {
      environment.cloudMode = true;

      await service.load();

      httpMock.expectNone(r => r.url.startsWith('rest/frontend_init'));
      expect(service.hasConnectionOverride).toBeFalse();
    });

    it('exposes the environment.cloud values through the getters', async () => {
      environment.cloudMode = true;
      environment.protocol = 'https';
      environment.apiUrl = 'cloud.host';
      environment.apiPort = 4000;

      await service.load();

      expect(service.protocol).toBe('https');
      expect(service.apiUrl).toBe('cloud.host');
      expect(service.apiPort).toBe(4000);
    });
  });

  /* ------------------------------------------- NON-CLOUD: SUCCESSFUL LOADS ----------------------------------------- */

  describe('non-cloud – valid files', () => {
    it('uses every field from a complete runtime config', async () => {
      await loadWith({ protocol: 'https', apiUrl: 'cmdb.example.com', apiPort: 4000 });

      expect(service.hasConnectionOverride).toBeTrue();
      expect(service.protocol).toBe('https');
      expect(service.apiUrl).toBe('cmdb.example.com');
      expect(service.apiPort).toBe(4000);
    });

    it('accepts apiPort provided as a numeric string', async () => {
      await loadWith({ protocol: 'http', apiUrl: '192.168.64.21', apiPort: '2100' });

      expect(service.apiPort).toBe(2100);
      expect(service.apiUrl).toBe('192.168.64.21');
    });

    it('is NOT an override when protocol/port are blank (all three required)', async () => {
      await loadWith({ protocol: '', apiUrl: 'only-host', apiPort: '' });

      expect(service.hasConnectionOverride).toBeFalse();
      expect(service.apiUrl).toBe('only-host'); // getter still exposes the parsed host
    });

    it('treats an all-empty file as "not set" and behaves like no override', async () => {
      await loadWith({ protocol: '', apiUrl: '', apiPort: '' });

      expect(service.hasConnectionOverride).toBeFalse();
      expect(service.protocol).toBe('http');
      expect(service.apiUrl).toBe('env-host');
      expect(service.apiPort).toBe(9999);
    });

    it('ignores a port-only file because a host is required for an override', async () => {
      await loadWith({ apiPort: 2100 });

      expect(service.hasConnectionOverride).toBeFalse();
    });

    it('accepts an IPv6 host in bracket notation', async () => {
      await loadWith({ protocol: 'http', apiUrl: '[::1]', apiPort: 4000 });

      expect(service.apiUrl).toBe('[::1]');
      expect(service.hasConnectionOverride).toBeTrue();
    });
  });

  /* ----------------------------------------------- NON-CLOUD: SANITIZING ------------------------------------------- */

  describe('non-cloud – sanitizing untrusted values', () => {
    it('lower-cases and trims the protocol', async () => {
      await loadWith({ protocol: '  HTTPS  ', apiUrl: 'host' });
      expect(service.protocol).toBe('https');
    });

    it('drops an unknown protocol and keeps the environment default', async () => {
      await loadWith({ protocol: 'ftp', apiUrl: 'host' });
      expect(service.protocol).toBe('http');
    });

    it('rejects a javascript: protocol', async () => {
      await loadWith({ protocol: 'javascript', apiUrl: 'host' });
      expect(service.protocol).toBe('http');
    });

    it('strips a scheme prefix from the host', async () => {
      await loadWith({ apiUrl: 'https://host.example' });
      expect(service.apiUrl).toBe('host.example');
    });

    it('strips a trailing slash from the host', async () => {
      await loadWith({ apiUrl: 'host.example/' });
      expect(service.apiUrl).toBe('host.example');
    });

    it('rejects a host that contains a path', async () => {
      await loadWith({ apiUrl: 'host.example/api' });
      expect(service.hasConnectionOverride).toBeFalse();
      expect(service.apiUrl).toBe('env-host');
    });

    it('rejects a host with whitespace', async () => {
      await loadWith({ apiUrl: 'ho st' });
      expect(service.hasConnectionOverride).toBeFalse();
    });

    it('rejects a javascript: payload in the host', async () => {
      await loadWith({ apiUrl: 'javascript:alert(1)' });
      expect(service.hasConnectionOverride).toBeFalse();
    });

    it('ignores a non-string host', async () => {
      await loadWith({ apiUrl: 12345 as unknown as string });
      expect(service.hasConnectionOverride).toBeFalse();
    });

    it('allows port 0 (meaning "no explicit port")', async () => {
      await loadWith({ apiUrl: 'host', apiPort: 0 });
      expect(service.apiPort).toBe(0);
    });

    it('drops a port above the valid range', async () => {
      await loadWith({ apiUrl: 'host', apiPort: 99999 });
      expect(service.apiPort).toBe(9999); // environment default
    });

    it('drops a negative port', async () => {
      await loadWith({ apiUrl: 'host', apiPort: -1 });
      expect(service.apiPort).toBe(9999);
    });

    it('drops a non-numeric port', async () => {
      await loadWith({ apiUrl: 'host', apiPort: 'abc' as unknown as number });
      expect(service.apiPort).toBe(9999);
    });

    it('drops a non-integer port', async () => {
      await loadWith({ apiUrl: 'host', apiPort: 40.5 });
      expect(service.apiPort).toBe(9999);
    });
  });

  /* ------------------------------------------ NON-CLOUD: MISSING / BROKEN FILE ------------------------------------- */

  describe('non-cloud – missing or malformed files', () => {
    it('falls back to environment on HTTP 404', async () => {
      const pending = service.load();
      const req = httpMock.expectOne(r => r.url.startsWith('rest/frontend_init'));
      req.flush('Not Found', { status: 404, statusText: 'Not Found' });
      await pending;

      expect(service.hasConnectionOverride).toBeFalse();
      expect(service.protocol).toBe('http');
      expect(service.apiUrl).toBe('env-host');
      expect(service.apiPort).toBe(9999);
    });

    it('falls back to environment on a network error', async () => {
      const pending = service.load();
      const req = httpMock.expectOne(r => r.url.startsWith('rest/frontend_init'));
      req.error(new ProgressEvent('error'));
      await pending;

      expect(service.hasConnectionOverride).toBeFalse();
      expect(service.apiUrl).toBe('env-host');
    });

    it('ignores a null response body', async () => {
      await loadWith(null);
      expect(service.hasConnectionOverride).toBeFalse();
    });

    it('ignores an array response body', async () => {
      await loadWith(['not', 'an', 'object'] as unknown as RuntimeConnectionConfig);
      expect(service.hasConnectionOverride).toBeFalse();
    });

    it('ignores a primitive response body', async () => {
      await loadWith(42 as unknown as RuntimeConnectionConfig);
      expect(service.hasConnectionOverride).toBeFalse();
    });
  });

  /* --------------------------------------------------- REQUEST SHAPE ----------------------------------------------- */

  describe('request behaviour', () => {
    it('requests the runtime config with a cache-busting query parameter', async () => {
      const pending = service.load();
      const req = httpMock.expectOne(r => r.url.startsWith('rest/frontend_init'));

      expect(req.request.method).toBe('GET');
      expect(req.request.urlWithParams).toContain('v=');

      req.flush({});
      await pending;
    });

    it('fetches only once even when load() is called repeatedly', async () => {
      await loadWith({ apiUrl: 'host' });

      await service.load();

      httpMock.expectNone(r => r.url.startsWith('rest/frontend_init'));
      expect(service.apiUrl).toBe('host');
    });
  });

  /* --------------------------------------------------- EDGE CASES -------------------------------------------------- */

  describe('edge cases & robustness', () => {
    it('returns environment defaults before load() is ever called', () => {
      expect(service.hasConnectionOverride).toBeFalse();
      expect(service.protocol).toBe('http');
      expect(service.apiUrl).toBe('env-host');
      expect(service.apiPort).toBe(9999);
    });

    it('keeps the file protocol even when no host is provided (no override)', async () => {
      await loadWith({ protocol: 'https' });

      expect(service.hasConnectionOverride).toBeFalse();
      expect(service.protocol).toBe('https');
    });

    it('rejects a whitespace-only host', async () => {
      await loadWith({ apiUrl: '   ' });
      expect(service.hasConnectionOverride).toBeFalse();
    });

    it('trims surrounding whitespace from the host', async () => {
      await loadWith({ apiUrl: '  cmdb.example.com  ' });
      expect(service.apiUrl).toBe('cmdb.example.com');
    });

    it('preserves the case of the host', async () => {
      await loadWith({ apiUrl: 'CMDB.Example.COM' });
      expect(service.apiUrl).toBe('CMDB.Example.COM');
    });

    it('ignores unknown extra keys', async () => {
      await loadWith(
        { protocol: 'http', apiUrl: 'host', apiPort: 4000, tenant: 'acme', debug: true } as RuntimeConnectionConfig
      );

      expect(service.apiUrl).toBe('host');
      expect(service.hasConnectionOverride).toBeTrue();
    });

    it('keeps an embedded port on the host while stripping scheme and trailing slash', async () => {
      await loadWith({ apiUrl: 'http://host.example:8080/' });
      expect(service.apiUrl).toBe('host.example:8080');
    });

    it('accepts a numeric string port with surrounding whitespace', async () => {
      await loadWith({ apiUrl: 'host', apiPort: ' 2100 ' });
      expect(service.apiPort).toBe(2100);
    });

    it('accepts the string "0" as port 0', async () => {
      await loadWith({ apiUrl: 'host', apiPort: '0' });
      expect(service.apiPort).toBe(0);
    });

    it('rejects a whitespace-only port string', async () => {
      await loadWith({ apiUrl: 'host', apiPort: '   ' });
      expect(service.apiPort).toBe(9999);
    });

    it('rejects a boolean port', async () => {
      await loadWith({ apiUrl: 'host', apiPort: true as unknown as number });
      expect(service.apiPort).toBe(9999);
    });

    it('rejects an array port', async () => {
      await loadWith({ apiUrl: 'host', apiPort: [] as unknown as number });
      expect(service.apiPort).toBe(9999);
    });

    it('rejects an object port', async () => {
      await loadWith({ apiUrl: 'host', apiPort: {} as unknown as number });
      expect(service.apiPort).toBe(9999);
    });

    it('accepts the maximum valid port 65535', async () => {
      await loadWith({ apiUrl: 'host', apiPort: 65535 });
      expect(service.apiPort).toBe(65535);
    });

    it('rejects the port 65536 (just out of range)', async () => {
      await loadWith({ apiUrl: 'host', apiPort: 65536 });
      expect(service.apiPort).toBe(9999);
    });

    it('falls back to environment on HTTP 500', async () => {
      const pending = service.load();
      const req = httpMock.expectOne(r => r.url.startsWith('rest/frontend_init'));
      req.flush('Server Error', { status: 500, statusText: 'Server Error' });
      await pending;

      expect(service.hasConnectionOverride).toBeFalse();
      expect(service.apiUrl).toBe('env-host');
    });

    it('falls back to environment on HTTP 403', async () => {
      const pending = service.load();
      const req = httpMock.expectOne(r => r.url.startsWith('rest/frontend_init'));
      req.flush('Forbidden', { status: 403, statusText: 'Forbidden' });
      await pending;

      expect(service.hasConnectionOverride).toBeFalse();
    });

    it('ignores a string response body', async () => {
      await loadWith('just a string' as unknown as RuntimeConnectionConfig);
      expect(service.hasConnectionOverride).toBeFalse();
    });

    it('does not fetch a second time in cloud mode', async () => {
      environment.cloudMode = true;

      await service.load();
      await service.load();

      httpMock.expectNone(r => r.url.startsWith('rest/frontend_init'));
    });

    it('is NOT an override when some fields are invalid and get dropped', async () => {
      await loadWith({ protocol: 'ftp', apiUrl: 'good.host', apiPort: 999999 });

      // protocol + port are invalid → dropped → incomplete → ignored entirely.
      expect(service.hasConnectionOverride).toBeFalse();
      expect(service.apiUrl).toBe('good.host'); // getter still exposes the parsed host
    });
  });

  /* --------------------------------------- ADDITIONAL REALISTIC SCENARIOS ------------------------------------------ */

  describe('additional realistic scenarios', () => {
    // ---- protocol variants ----
    it('normalises mixed-case protocol "Http"', async () => {
      await loadWith({ protocol: 'Http', apiUrl: 'host' });
      expect(service.protocol).toBe('http');
    });

    it('normalises mixed-case protocol "Https"', async () => {
      await loadWith({ protocol: 'Https', apiUrl: 'host' });
      expect(service.protocol).toBe('https');
    });

    it('trims tab/newline whitespace around the protocol', async () => {
      await loadWith({ protocol: '\thttps\n', apiUrl: 'host' });
      expect(service.protocol).toBe('https');
    });

    it('drops a null protocol', async () => {
      await loadWith({ protocol: null as unknown as string, apiUrl: 'host' });
      expect(service.protocol).toBe('http');
    });

    it('drops a numeric protocol', async () => {
      await loadWith({ protocol: 8080 as unknown as string, apiUrl: 'host' });
      expect(service.protocol).toBe('http');
    });

    it('drops a "ws" protocol', async () => {
      await loadWith({ protocol: 'ws', apiUrl: 'host' });
      expect(service.protocol).toBe('http');
    });

    it('drops a "wss" protocol', async () => {
      await loadWith({ protocol: 'wss', apiUrl: 'host' });
      expect(service.protocol).toBe('http');
    });

    // ---- host variants ----
    it('accepts "localhost"', async () => {
      await loadWith({ apiUrl: 'localhost' });
      expect(service.apiUrl).toBe('localhost');
    });

    it('accepts a loopback IPv4 address', async () => {
      await loadWith({ apiUrl: '127.0.0.1' });
      expect(service.apiUrl).toBe('127.0.0.1');
    });

    it('accepts a host with an embedded port', async () => {
      await loadWith({ apiUrl: '10.0.0.5:8080' });
      expect(service.apiUrl).toBe('10.0.0.5:8080');
    });

    it('accepts a multi-level subdomain', async () => {
      await loadWith({ apiUrl: 'api.cmdb.example.com' });
      expect(service.apiUrl).toBe('api.cmdb.example.com');
    });

    it('strips an uppercase scheme from the host', async () => {
      await loadWith({ apiUrl: 'HTTP://Host.COM' });
      expect(service.apiUrl).toBe('Host.COM');
    });

    it('collapses multiple trailing slashes', async () => {
      await loadWith({ apiUrl: 'host.example///' });
      expect(service.apiUrl).toBe('host.example');
    });

    it('rejects a host containing an underscore', async () => {
      await loadWith({ apiUrl: 'host_name' });
      expect(service.hasConnectionOverride).toBeFalse();
    });

    it('rejects a host embedding credentials (@)', async () => {
      await loadWith({ apiUrl: 'user@evil.host' });
      expect(service.hasConnectionOverride).toBeFalse();
    });

    it('rejects a host containing a query string', async () => {
      await loadWith({ apiUrl: 'host?redirect=evil' });
      expect(service.hasConnectionOverride).toBeFalse();
    });

    it('rejects a host containing angle brackets', async () => {
      await loadWith({ apiUrl: '<script>alert(1)</script>' });
      expect(service.hasConnectionOverride).toBeFalse();
    });

    it('rejects a host containing non-ASCII characters', async () => {
      await loadWith({ apiUrl: 'höst.example' });
      expect(service.hasConnectionOverride).toBeFalse();
    });

    it('ignores a boolean host', async () => {
      await loadWith({ apiUrl: true as unknown as string });
      expect(service.hasConnectionOverride).toBeFalse();
    });

    // ---- port variants ----
    it('accepts port 443 as a number', async () => {
      await loadWith({ apiUrl: 'host', apiPort: 443 });
      expect(service.apiPort).toBe(443);
    });

    it('accepts port "443" as a string', async () => {
      await loadWith({ apiUrl: 'host', apiPort: '443' });
      expect(service.apiPort).toBe(443);
    });

    it('accepts port 80', async () => {
      await loadWith({ apiUrl: 'host', apiPort: 80 });
      expect(service.apiPort).toBe(80);
    });

    it('accepts an integer-valued float 3.0 as 3', async () => {
      await loadWith({ apiUrl: 'host', apiPort: 3.0 });
      expect(service.apiPort).toBe(3);
    });

    it('rejects Infinity as a port', async () => {
      await loadWith({ apiUrl: 'host', apiPort: Infinity as unknown as number });
      expect(service.apiPort).toBe(9999);
    });

    it('rejects NaN as a port', async () => {
      await loadWith({ apiUrl: 'host', apiPort: NaN as unknown as number });
      expect(service.apiPort).toBe(9999);
    });

    it('rejects a port far above the range', async () => {
      await loadWith({ apiUrl: 'host', apiPort: 70000 });
      expect(service.apiPort).toBe(9999);
    });

    // ---- realistic deployment files ----
    it('handles a typical HTTPS reverse-proxy deployment (port 0 = no port segment)', async () => {
      await loadWith({ protocol: 'https', apiUrl: 'cmdb.company.com', apiPort: 0 });
      expect(service.protocol).toBe('https');
      expect(service.apiUrl).toBe('cmdb.company.com');
      expect(service.apiPort).toBe(0);
      expect(service.hasConnectionOverride).toBeTrue();
    });

    it('handles a typical HTTPS deployment on port 443', async () => {
      await loadWith({ protocol: 'https', apiUrl: 'cmdb.company.com', apiPort: 443 });
      expect(service.protocol).toBe('https');
      expect(service.apiUrl).toBe('cmdb.company.com');
      expect(service.apiPort).toBe(443);
    });

    it('handles a typical on-prem HTTP deployment by IP and port', async () => {
      await loadWith({ protocol: 'http', apiUrl: '10.20.30.40', apiPort: 4000 });
      expect(service.apiUrl).toBe('10.20.30.40');
      expect(service.apiPort).toBe(4000);
    });

    it('is NOT an override when the port key is absent', async () => {
      await loadWith({ protocol: 'https', apiUrl: 'cmdb.company.com' });
      expect(service.hasConnectionOverride).toBeFalse();
    });

    // ---- loading behaviour ----
    it('collapses concurrent load() calls into a single request', async () => {
      const p1 = service.load();
      const p2 = service.load();
      const req = httpMock.expectOne(r => r.url.startsWith('rest/frontend_init'));
      req.flush({ apiUrl: 'host' });
      await Promise.all([p1, p2]);
      expect(service.apiUrl).toBe('host');
    });

    it('falls back to environment on HTTP 401', async () => {
      const pending = service.load();
      const req = httpMock.expectOne(r => r.url.startsWith('rest/frontend_init'));
      req.flush('Unauthorized', { status: 401, statusText: 'Unauthorized' });
      await pending;
      expect(service.hasConnectionOverride).toBeFalse();
    });
  });

  /* ---------------------------------------- OVERRIDE COMPLETENESS (ALL-OR-NOTHING) --------------------------------- */

  describe('override completeness (all-or-nothing)', () => {
    it('activates only when protocol, host and port are all present', async () => {
      await loadWith({ protocol: 'https', apiUrl: 'host', apiPort: 4000 });
      expect(service.hasConnectionOverride).toBeTrue();
    });

    it('does not activate when the protocol is missing', async () => {
      await loadWith({ apiUrl: 'host', apiPort: 4000 });
      expect(service.hasConnectionOverride).toBeFalse();
    });

    it('does not activate when the host is missing', async () => {
      await loadWith({ protocol: 'https', apiPort: 4000 });
      expect(service.hasConnectionOverride).toBeFalse();
    });

    it('does not activate when the port is missing', async () => {
      await loadWith({ protocol: 'https', apiUrl: 'host' });
      expect(service.hasConnectionOverride).toBeFalse();
    });

    it('does not activate when only the host is provided', async () => {
      await loadWith({ apiUrl: 'host' });
      expect(service.hasConnectionOverride).toBeFalse();
    });

    it('treats port 0 as a provided value (no port segment)', async () => {
      await loadWith({ protocol: 'https', apiUrl: 'host', apiPort: 0 });
      expect(service.hasConnectionOverride).toBeTrue();
      expect(service.apiPort).toBe(0);
    });

    it('does not activate when a provided field is invalid and dropped', async () => {
      await loadWith({ protocol: 'ftp', apiUrl: 'host', apiPort: 4000 });
      expect(service.hasConnectionOverride).toBeFalse();
    });
  });
});
