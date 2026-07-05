import { enableProdMode } from '@angular/core';
import { platformBrowserDynamic } from '@angular/platform-browser-dynamic';

import { AppModule } from './app/app.module';
import { environment } from './environments/environment';

if (environment.production) {
  enableProdMode();
}

/**
 * On the OIDC callback the SPA is loaded fresh via a full browser redirect. Angular's bootstrap
 * fires authenticated requests (e.g. the footer's system info) before OidcCallbackComponent can
 * process the fragment - those would 401 and trigger the global logout. Seed the session from the
 * URL fragment here, before bootstrap, so every request already carries the Bearer token.
 */
function primeOidcSession(): void {
  try {
    if (!window.location.pathname.includes('oidc-callback')) {
      return;
    }

    const hash = window.location.hash.startsWith('#') ? window.location.hash.substring(1) : '';
    const params = new URLSearchParams(hash);
    const token = params.get('token');
    const user = params.get('user');

    if (!token || !user) {
      return;
    }

    localStorage.setItem('current-user', user);
    localStorage.setItem('access-token', JSON.stringify({
      token,
      issued: Number(params.get('token_issued_at')),
      expire: Number(params.get('token_expire'))
    }));
  } catch {
    // Ignore - OidcCallbackComponent re-parses the fragment and surfaces any error.
  }
}

primeOidcSession();

platformBrowserDynamic().bootstrapModule(AppModule)
  .catch(err => console.error(err));
