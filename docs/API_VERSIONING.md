# API Versioning Policy

## Current Version

All API endpoints are served under the `/api/v1/` prefix.

**Stability guarantee**: The v1 API is stable. No breaking changes will be made without:
1. A 90-day deprecation notice communicated via email and release notes.
2. A `Deprecation` response header on all affected endpoints.
3. A `Sunset` response header specifying the exact removal date.

---

## Version Lifecycle

| Phase | Duration | Description |
|---|---|---|
| **Active** | Indefinite | Fully supported, receives bug fixes and security patches |
| **Deprecated** | ≥ 90 days | Still functional; `Deprecation` + `Sunset` headers added; migration guide published |
| **Sunset** | — | Version removed; requests return `410 Gone` |

---

## Breaking vs Non-Breaking Changes

### Breaking changes (require new API version)
- Removing or renaming a field in a response body
- Changing a field's type (e.g., `string` → `integer`)
- Removing an endpoint
- Changing an HTTP method (e.g., `GET` → `POST`)
- Making an optional field required
- Changing authentication requirements

### Non-breaking changes (safe to deploy without a version bump)
- Adding new optional fields to request/response bodies
- Adding new endpoints
- Adding new query parameters (all optional)
- Adding new error codes
- Narrowing the accepted value range (only if it was previously documented as unbounded)

---

## Deprecation Headers

When an endpoint is deprecated, the API will include these response headers:

```
Deprecation: true
Sunset: Sat, 01 Jan 2028 00:00:00 GMT
Link: <https://docs.yourcompany.com/api/migration/v1-to-v2>; rel="deprecation"
```

Clients should monitor for these headers and alert their teams when received.

---

## Versioning Strategy: URL Path

We use URL path versioning (`/api/v1/`, `/api/v2/`) rather than header-based versioning.

**Rationale:**
- Visible in logs, network traces, and browser history without special tooling
- Cache-friendly
- Easier for customer SDKs and curl scripts to reason about

---

## Future v2 Planning

When v2 is created, v1 will enter the **Deprecated** phase. The expected changes motivating v2 are tracked in [ROADMAP.md](../ROADMAP.md). Customers will receive migration guides before v1 enters the Deprecated phase.

---

## SDK Compatibility

Official SDKs will pin to a specific API version. A version mismatch between the SDK and the server will return:

```json
{
  "error": {
    "code": "API_VERSION_MISMATCH",
    "message": "This SDK targets API v1 but the server is on v2.",
    "recovery_hint": "Update your SDK to the latest version."
  }
}
```

---

## Changelog

| Date | Version | Change |
|---|---|---|
| 2026-02-25 | v1 | Initial stable release |
