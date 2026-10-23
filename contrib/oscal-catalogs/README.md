# OSCAL catalogs without an upstream OSCAL source

`build_catalogs.py` generates two of the catalogs bundled in `app/src/assets/oscal/catalogs/` and updates
their entries in `manifest.json`:

| Catalog | File | Content |
|---|---|---|
| NIS2 | `eu-nis2.json` | Directive (EU) 2022/2555 Art. 20, 21 (1-4), 23 (1-4) and the annex of Implementing Regulation (EU) 2024/2690, German, official text |
| ISO/IEC 27001:2022 Annex A | `iso-27001-2022-annex-a.json` | the 93 control numbers and titles only - the control text is ISO copyright |

```
python3 contrib/oscal-catalogs/build_catalogs.py                  # downloads the EU texts from the Publications Office
python3 contrib/oscal-catalogs/build_catalogs.py --nis2-dir DIR   # DIR holds 32022L2555.xhtml and 32024R2690.xhtml
```

The output is deterministic (uuid5 ids), so a rebuild of unchanged texts produces identical files.
Licences: `app/src/assets/oscal/licenses/eu-legal-texts-reuse.txt`, `iso-27001-titles-only.txt`, `NOTICE.txt`.
