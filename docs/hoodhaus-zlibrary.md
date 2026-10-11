# Z-Library in the HoodHaus fork

The Z-Library provider uses the JSON API with `z-lib.gd` as its default domain.
Leave **Settings → Downloads → Direct Download → Z-Library → Custom Domain**
blank to use that default. A saved custom domain overrides it for login,
search, and download-link resolution. Use a hostname such as `z-lib.gd`, or an
HTTPS origin without a port or path.

An explicit override is exclusive. The provider does not try other mirrors,
follow API redirects, or adopt advertised personal domains. If the selected
domain is blocked or unreachable, fix the field instead of expecting fallback.
The existing saved email and password are used only on the selected domain.
Session cookies are scoped to that domain. The API can return a signed HTTPS
file link on a different host; account cookies are not copied to that host.

Search results retain stable book URLs. The direct-download handler logs in
and resolves a fresh file link when the download starts, then uses its existing
streaming, cancellation, progress, and import path. If the custom domain
changes after a search, search again before downloading the old result.

The connection test checks authentication. It does not download a book or
prove that account quota or a particular file is available. FlareSolverr is
not used for Z-Library API requests. Anna's Archive retains its existing flow.

Validated on 11 October 2026 through the existing NAS VPN route: API login,
search, file-link resolution, and a complete public-domain EPUB download in
an isolated process using the revised provider and direct handler. The EPUB
archive and mimetype were checked, then the temporary file was removed.
No library import or live database write was performed.
