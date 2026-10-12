# OSCAL viewer (bundled in `app/src/assets/oscal/viewer/`)

The ISMS "Catalogs" page shows OSCAL catalogs with a static build of the OSCAL viewer
behind https://viewer.oscal.io (GitHub: `EasyDynamics/oscal-viewer`, MIT license, see
`app/src/assets/oscal/licenses/oscal-viewer-MIT.txt`).

The build in the repo is upstream `main` as of 2026-10-08 with
`oscal-viewer-datagerry-offline.patch` applied:

- hash routing and a relative base path, so it can be served from `/assets/oscal/viewer/`
- Google Analytics, the cookie banner and the Google Fonts import removed (no external requests)
- document load timeout raised from 10 s to 120 s (the large catalogs)
- documents are only loaded from the origin serving the viewer (`?url=` to foreign hosts is refused)
- DataGerry colour scheme

## Rebuild

```sh
git clone https://github.com/EasyDynamics/oscal-viewer.git && cd oscal-viewer
git checkout <main as of 2026-10-08>
patch -p2 < /path/to/contrib/oscal-viewer/oscal-viewer-datagerry-offline.patch
npm ci && npm run build
rm -rf <repo>/app/src/assets/oscal/viewer && cp -r dist <repo>/app/src/assets/oscal/viewer
```

The bundled catalogs, their sources and licenses are listed in
`app/src/assets/oscal/catalogs/manifest.json` and `app/src/assets/oscal/licenses/NOTICE.txt`.
