# Versioning

This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html):
`MAJOR.MINOR.PATCH`, judged against the public contract — the REST API, the
import formats, and the DB schema.

- **MAJOR** — incompatible changes: an endpoint or field removed or renamed, a
  response shape changed, a migration that can't be rolled forward.
- **MINOR** — backwards-compatible additions: a new adapter, page, or optional
  field. Also deprecations that still work.
- **PATCH** — backwards-compatible bug fixes only, no new surface.

Bump one number and reset those to its right (`0.14.0` → `0.15.0`). Released
versions are never edited — a mistake gets a new patch.

While MAJOR is `0` the API is not stable: breaking changes take a MINOR bump,
everything else a PATCH.

The bump follows the commits since the last release — any `feat:` → MINOR,
otherwise PATCH; a `!` or `BREAKING CHANGE:` footer → MAJOR (MINOR while `0.x`).

## Where the version lives

Three files carry the version and move together, in one commit:

- `package.json` (root)
- `apps/web/package.json`
- `apps/api/src/open_leprechaun/__init__.py` (`__version__`) — not
  `apps/api/pyproject.toml`, which declares `dynamic = ["version"]` and reads
  it from there.

A deployed instance shows its version through `RELEASE_VERSION`, which the
deployment sets; development ignores these numbers and shows the checked-out
commit instead.
