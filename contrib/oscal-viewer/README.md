# OSCAL viewer (bundled in `app/src/assets/oscal/viewer/`)

The ISMS "Catalogs" page shows OSCAL catalogs with a static build of the OSCAL viewer
behind https://viewer.oscal.io (GitHub: `EasyDynamics/oscal-viewer`, MIT license, see
`app/src/assets/oscal/licenses/oscal-viewer-MIT.txt`).

The build in the repo is upstream `main` at commit
`89f73c414a6c20a6e0942c9a199675ce9fef3db9` (2026-10-08, "fix: resolve profile control
selection ... (#122)") with `oscal-viewer-datagerry-offline.patch` applied.

## What the patch changes

Offline / security:

- hash routing and a relative base path (`base: './'`), so it can be served from `/assets/oscal/viewer/`
- Google Analytics, the cookie banner, the page-view tracking and the Google Fonts import removed
  (no external requests); `staticwebapp.config.json` (Azure hosting) removed
- document load timeout raised from 10 s to 120 s (the large catalogs)
- documents are only loaded from the origin serving the viewer (`?url=` to foreign hosts is refused)
- no oscal.io services: the access-token (JWT) UI is gone and no request is ever treated as an
  `api.oscal.io` / `registry.oscal.io` request (no credentials, no bearer token)

Read-only catalog viewer:

- only the catalog page is routed; home (upload / registry), profile, component definition, SSP,
  assessment plan/results, POA&M, docs and privacy pages are not reachable (every other path
  redirects to `#/catalog`, keeping the query string). This also drops mermaid from the bundle.
- no "New File" button, no drag-and-drop upload and no "load from URL" form; without a catalog the
  page only says to open one from ISMS › Catalogs (or shows the load error)
- catalog browsing, search, overview/metadata, control details (statements, guidance, parameters,
  properties, links between controls, back matter) are unchanged

DATAGERRY look (`src/theme/themes/datagerry.ts`, selected in `.env` and as the default in
`src/theme/themeConfig.ts`; the oscal.io / Easy Dynamics themes are not compiled in):

- colours from DATAGERRY's SCSS: `$primary` #e94d18 (accent, links, active tree item, parameter
  pills), `$cmdb-secondary` #fbba00, body text #212529, muted #6c757d, Bootstrap borders #dee2e6,
  sidebar surface #f9f9fb, breadcrumb/footer grey #f2f2f2, Bootstrap success/danger colours
- font: Raleway 300/400/600/700 (the woff2 files DATAGERRY ships in `app/src/assets/fonts`,
  bundled into the viewer build), Bootstrap's monospace system stack, 14px base size, light headings
- square corners (`$border-radius: 0`), flat bordered cards instead of shadows, pill badges,
  Bootstrap-style search input, focus ring and bordered/striped prose tables, thin primary scrollbar
- light only (DATAGERRY has no dark mode); the theme toggle is removed and OS/stored preferences
  are ignored
- branding: DATAGERRY favicon and logo, page title `<catalog title> - DATAGERRY`; no OSCAL.io logo,
  tagline, footer links, "Content Registry" link or model tab bar
- layout: `embedded=1` in the hash query (set by DATAGERRY for the iframe on the catalog page)
  hides the viewer's own header and padding so the catalog fills the frame; without it (the
  "New Tab" view) a slim white header with the DATAGERRY logo, the catalog title and the 2px
  orange rule of the DATAGERRY navbar is shown

## Rebuild

```sh
git clone https://github.com/EasyDynamics/oscal-viewer.git && cd oscal-viewer
git checkout 89f73c414a6c20a6e0942c9a199675ce9fef3db9
patch -p2 < <repo>/contrib/oscal-viewer/oscal-viewer-datagerry-offline.patch
# binary files are not part of the patch:
rm public/favicon-oscalio-16.png
mkdir -p src/theme/fonts
for w in Light Regular SemiBold Bold; do
  cp <repo>/app/src/assets/fonts/Raleway-$w.woff2 <repo>/app/src/assets/fonts/Raleway-$w-Ext.woff2 src/theme/fonts/
done
cp <repo>/app/src/assets/img/favicon-32x32.png public/favicon.png
npm ci && npm run build
rm -rf <repo>/app/src/assets/oscal/viewer && cp -r dist <repo>/app/src/assets/oscal/viewer
```

The result is byte-identical to the committed build. Afterwards check that the build makes no
external requests, e.g. `grep -rE 'googletagmanager|googleapis|fonts.gstatic|api.oscal.io|registry.oscal.io' app/src/assets/oscal/viewer`
must find nothing (`http://oscal.io/ns` is an OSCAL property namespace identifier, not a request).

To regenerate the patch, unpack the pristine upstream commit to `orig/oscal-viewer-main` and the
modified tree to `build/oscal-viewer-main`, then:

```sh
diff -ruN -x node_modules -x dist -x '*.tsbuildinfo' -x '*.woff2' -x '*.png' \
  orig/oscal-viewer-main build/oscal-viewer-main > oscal-viewer-datagerry-offline.patch
```

The bundled catalogs, their sources and licenses are listed in
`app/src/assets/oscal/catalogs/manifest.json` and `app/src/assets/oscal/licenses/NOTICE.txt`.
