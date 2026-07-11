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
import { Injectable, inject } from '@angular/core';
import { HttpBackend, HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

import { environment } from 'src/environments/environment';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Shape of the optional runtime connection file served at /app-config.json. */
export interface RuntimeConnectionConfig {
  protocol?: string;
  apiUrl?: string;
  apiPort?: number | string;
}

/**
 * Loads optional runtime connection settings from `app-config.json` (served at the web root).
 */
@Injectable({ providedIn: 'root' })
export class RuntimeConfigService {
  private static readonly CONFIG_PATH = 'app-config.json';
  private static readonly ALLOWED_PROTOCOLS = ['http', 'https'];

  // Dedicated client on the raw backend so the config load never triggers auth/error interceptors.
  private readonly http = new HttpClient(inject(HttpBackend));

  private overrides: RuntimeConnectionConfig = {};
  private loaded = false;

  /** Effective protocol: runtime override, otherwise the environment default. */
  get protocol(): string {
    return (this.overrides.protocol as string) || environment.protocol;
  }

  /** Effective host without scheme: runtime override, otherwise the environment default. */
  get apiUrl(): string {
    return (this.overrides.apiUrl as string) ?? environment.apiUrl;
  }

  /** Effective port (0 means "no explicit port"): runtime override, otherwise the environment default. */
  get apiPort(): number {
    return (this.overrides.apiPort as number) ?? environment.apiPort;
  }

  /**
   * True only when the file supplies a COMPLETE connection — protocol, host AND port. A partial
   * file never takes effect and is never blended with the environment defaults; the operator must
   * specify all three (use port 0 for "no port segment").
   */
  get hasConnectionOverride(): boolean {
    return (
      this.overrides.protocol !== undefined &&
      this.overrides.apiUrl !== undefined &&
      this.overrides.apiPort !== undefined
    );
  }

  /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

  /**
   * Fetches and validates the runtime config file. Invoked once from an APP_INITIALIZER so the
   * connection settings are ready before any service reads them. Cloud mode short-circuits because
   * its connection is baked in through `environment.cloud.ts`.
   */
  public async load(): Promise<void> {
    if (this.loaded) {
      return;
    }
    this.loaded = true;

    if (environment.cloudMode) {
      return;
    }

    try {
      const raw = await firstValueFrom(
        this.http.get<RuntimeConnectionConfig>(`${RuntimeConfigService.CONFIG_PATH}?v=${Date.now()}`)
      );
      this.overrides = this.sanitize(raw);
    } catch {
      // Missing or unreadable file is expected; fall back to environment defaults.
      this.overrides = {};
    }
  }

  /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  /**
   * Keeps only well-formed, safe values from the untrusted file. Anything invalid is dropped so the
   * corresponding environment default is used instead.
   */
  private sanitize(raw: RuntimeConnectionConfig | null): RuntimeConnectionConfig {
    if (!raw || typeof raw !== 'object') {
      return {};
    }

    const config: RuntimeConnectionConfig = {};

    const protocol = typeof raw.protocol === 'string' ? raw.protocol.trim().toLowerCase() : '';
    if (RuntimeConfigService.ALLOWED_PROTOCOLS.includes(protocol)) {
      config.protocol = protocol;
    }

    if (typeof raw.apiUrl === 'string') {
      const host = raw.apiUrl.trim().replace(/^https?:\/\//i, '').replace(/\/+$/, '');
      if (host && /^[a-z0-9.\-:\[\]]+$/i.test(host)) {
        config.apiUrl = host;
      }
    }

    const port = this.coercePort(raw.apiPort);
    if (port !== null) {
      config.apiPort = port;
    }

    return config;
  }

  private coercePort(value: unknown): number | null {
    if (typeof value === 'number') {
      return Number.isInteger(value) && value >= 0 && value <= 65535 ? value : null;
    }

    if (typeof value === 'string') {
      const trimmed = value.trim();

      if (!trimmed) {
        return null;
      }

      const port = Number(trimmed);
      return Number.isInteger(port) && port >= 0 && port <= 65535 ? port : null;
    }

    return null;
  }
}
