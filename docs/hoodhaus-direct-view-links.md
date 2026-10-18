# Direct-search browser links

Fork issue #10 reported that View opened the Z-Library homepage while direct
downloads worked. The provider constructed both info_url and download_url from
its numeric API ID/hash, and ignored the search result's browser href. The
source adapter passed info_url unchanged to the dialog, which rendered it.

A regression fixture supplies an opaque-token browser href alongside a numeric
API reference. Before this repair, provider.search returned the numeric
reference for both fields. The failing assertion exercised the actual HTTP
response mapping rather than a URL helper in isolation.

The selected scope was already approved in triage: use a valid provider-supplied
browser URL for View, retain the numeric ID/hash for downloads, and omit View
if no usable browser URL is available. The repair reads href, resolves relative
paths against the configured HTTPS domain, requires a book-details path on
that domain, and removes query/fragment parameters. It does not follow personal
or alternative domains or expose backend session parameters. Download URL
construction and API file resolution are unchanged.

The API href contract is supported by primary client implementations:

- [Calibre plugin, zlibrary_plugin.py](https://github.com/tekofx/zlibrary-calibre-store-plugin/blob/main/zlibrary_plugin.py)
  uses book['href'] for details and id/hash for API endpoints.
- [stumpzlib, zlibrary.go](https://github.com/tuckerwales/stumpzlib/blob/main/zlibrary.go)
  retains the API Href and resolves it separately as a browser page URL.

The current reported Station Eleven View URL is
https://z-lib.gd/book/2865528/b628a6. The user supplied
https://z-lib.gd/book/qlXkpNxNAa/station-eleven.html as a possible corresponding
browser entry based on size and search position. That edition relationship is
unverified; the repair must use each result's own href rather than infer it
from those observations. The test's numeric/opaque pairing is synthetic.

Public web retrieval of both reported URL forms returned Internal Error. No
live provider response, redirect chain or authenticated browser navigation was
captured. Fixture tests prove the mapping correction and unchanged download
resolution. After deployment, validate View on a pending result whose provider
supplies href; a result without a usable href should still be downloadable
with View omitted. No credentials, source settings, quota policy, automatic
selection rules or production data were changed during this investigation.
