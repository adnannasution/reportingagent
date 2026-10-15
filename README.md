"# reportingagent" 

## API data (baca-saja) untuk aplikasi lain — `/api/v1`

Data SAP hasil upload bisa ditarik aplikasi lain (mis. App-Rel) dengan kontrak yang sama seperti
API data Excellent Dashboard dan agentisomasterdata. Detail lengkap ada di `data_api.py`.

| Dataset | Isi |
|---|---|
| `sap-bom` | sap_bom: Bill of Materials SAP per equipment (komponen, deskripsi, kuantitas, satuan, item text, ...) |

Endpoint: `GET /api/v1/datasets`, `/api/v1/pages`, `/api/v1/datasets/{nama}` (berhalaman `limit`/`after`, filter
`?kolom=nilai`, `__in`, `__like`, ...), `/schema`, `/version`, `/export?format=ndjson|csv`.

Auth: header `X-API-Key`. Isi env `DATA_API_KEYS=apprel=<kunci>` di Railway (kosong = API terkunci, 503).
Opsional `DATA_API_RATE_PER_MIN` (bawaan 120). Endpoint ini tidak memakai login SSO.
