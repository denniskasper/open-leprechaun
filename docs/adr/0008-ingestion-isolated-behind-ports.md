# Ingestion is isolated behind ports, one per shape of source

## Status

accepted — extends v1's ADR-0004

## Context

Venues differ in authentication, pagination, rate limits, symbol formats and history windows, and
in how much they expose. v1 isolated exchange futures behind an adapter port. v2 must also ingest
from brokers, from exported files, and from a self-custody wallet that publishes neither an export
nor an account — only a chain and an address.

## Decision

Isolate every source behind a port emitting canonical, venue-agnostic normalized records, and
recognise that there are **four shapes**, not one: an **exchange adapter** and a **broker adapter**
(both authenticate against an account), a **CSV connector** (parses an exported file), and an
**Address Indexer** (takes a chain and an address, requires no credentials, and is read-only by
nature rather than by permission). Market data splits further into identifier resolution and
pricing, because no single provider does both well on a free tier.

No port touches the database, converts to EUR, or computes tax. Adding a venue is one
implementation plus a registry entry, with no change to any service, router or screen. Each port
has a fake, and each implementation is tested against recorded venue responses with no live calls
in CI.

Each connector declares the **timezone and units** its venue exports in and normalises on the way
in — an export in local time silently produces wrong tax years, and one in sub-units silently
produces wrong quantities.

## Considered Options

- **One universal ingestion port.** Rejected: an address has no credential and a file has no
  pagination; forcing them into one interface makes every implementation carry fields it cannot
  fill.
- **Let richer venues supply finished positions directly.** Rejected, as in v1: it creates two
  derivation modes and forks the tax path.

## Consequences

- Exactly one ingestion mode is declared authoritative **per Account**. A second source may
  reconcile against it but may not write transactions — which makes double-counting structurally
  impossible rather than merely unlikely.
- Adapters declare their capabilities, including maximum lookback, so the app can warn honestly
  about how far back a venue actually reaches.
