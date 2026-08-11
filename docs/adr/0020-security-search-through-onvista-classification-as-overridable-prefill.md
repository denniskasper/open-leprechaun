# Security search through onvista, classification as overridable prefill

## Status

accepted

## Context

The Admin adds a share or fund by searching for it (ticket 44), so instrument metadata is never
hand-typed where a provider knows it. The search must accept ISIN, WKN, ticker or name alike and
answer candidates carrying what creation needs: the identifiers, name, type, currency and the
primary listing. Beyond identity, a fund's taxation depends on its Teilfreistellung category
(§20 InvStG) — a value some providers state and none can be trusted to decide.

Candidate providers without a paid plan disagree on the essentials: OpenFIGI resolves
identifiers but answers FIGIs, not ISINs — a name search yields nothing creation can key on —
and carries no currency; Yahoo's search is unofficial and ISIN-less. onvista, a German market
portal, answers one keyless query endpoint that takes ISIN, WKN, ticker and name alike and
returns ISIN, WKN and ticker per candidate, with a per-candidate snapshot carrying currency,
primary market and — for funds — a fund-type and capitalisation vocabulary.

## Decision

Security search goes through **one port** (`ports/security_search.py`, per ADR-0008) whose
**onvista implementation** is the application's provider. One query serves every identifier
kind and names; each candidate is enriched from its snapshot, and a **snapshot failure degrades
that one candidate** to its query fields rather than failing the search.

The provider's fund vocabulary is mapped onto the §20 InvStG categories **only where the
mapping is defensible** — Aktienfonds, Mischfonds, Immobilienfonds, and the fund types that
carry no exemption, which map to `sonstige` as a statement, not an absence. Anything else
prefills nothing: **the classification is a prefill wearing the source `provider`, never a
verdict** — always overridable, and the Admin's own value is recorded with the source `admin`.
An unclassified fund blocks report finalisation rather than assuming a zero rate; the blocker
links the screen that classifies it.

Search failures reuse the price port's vocabulary: a rate limit is its own named condition,
distinct from an outage. onvista refuses the default python user agent outright, so the client
identifies itself honestly as `open-leprechaun`.

## Considered Options

- **OpenFIGI.** Rejected: search answers FIGIs, so a by-name result cannot create an ISIN-keyed
  Instrument (ADR-0010), and neither currency nor a Teilfreistellung hint is available.
- **No real provider until ticket 45.** Rejected: the port with only a fake satisfies tests but
  leaves the Admin hand-typing metadata — the exact failure the ticket names.
- **Deriving the category from the provider as authoritative.** Rejected: onvista's fund types
  describe investment focus, not the statute's thresholds. A prefill with its source shown keeps
  the Admin the deciding instance without retyping the common case.
- **Storing the rate instead of the category.** Rejected: rates are statutory values with years
  and legislative history; the fund's fact is its category, and the statutory store owns what a
  category is worth in a given year.

## Consequences

- Ticket 45's identifier-resolution and pricing ports remain free to choose different
  providers; nothing outside `ports/onvista.py` knows onvista's vocabulary.
- Extending the category mapping is one line in the provider port; an unmapped fund type simply
  prefills nothing and the fund waits for the Admin, guarded by the finalisation blocker.
- A provider outage leaves manual creation available; the Instrument is then unpriced —
  visible, and never valued at zero.
