# Changelog

## Unreleased (feature/live-data-integration)

- **Security and accounts:** sessions can be revoked (password reset, deactivation); same-origin check on every write;
  security headers and a content-security-policy; 8-character passwords; temporary passwords must be changed at first
  sign-in; manager sign-ups wait for the owner's approval; the invite code can be replaced; the first start generates a
  random admin password when none is configured.
- **Data integrity:** run state changes are atomic (a double tap cannot count fines twice); one active run per inspector
  is enforced by the database; SQLite runs in WAL mode with the indexes the pages need.
- **Field app:** requests time out instead of freezing; rides finished offline or on a server error are kept and sent
  later; the shift survives a restart; Web Push for new offers and the end of a break; zoom buttons and the menu under
  the thumb; dark theme; accessibility and RTL fixes; an installable app shell that works offline.
- **Manager console:** shared dialogs with focus trap and unsaved-change guard; bulk deactivate and export; edit,
  deactivate and CSV on a person's page; analytics range kept in the address; tab title shows how many things wait for
  you; CSV export protects against spreadsheet formulas.
- **Assets:** Font Awesome, Leaflet, Chart.js and the QR library are served from `app/static/vendor/` (no third-party
  CDN, works offline).
