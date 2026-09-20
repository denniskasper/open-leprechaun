# Income is recorded net, with withholding declared beside the legs

## Status

accepted

## Context

A dividend reaches an Account already reduced by taxes: a source country's Quellensteuer, and at a
withholding Depot the Kapitalertragsteuer with its surcharge and church tax. The §20 engine needs
the **gross** and each withheld component (ADR-0013); the ledger needs cash balances that match the
broker's, which only ever saw the **net**.

Legs are what moved through an Account (ADR-0011). The withheld amounts never did — they were taken
before the payment arrived — so they have no Account to leave and no lot to consume.

## Decision

The in-leg of a dividend, distribution or interest Transaction is the net that arrived. What was
taken out before it did is a **declaration on the Transaction**, stored beside the legs: the
security that paid, the Quellensteuer with its source country, and the German tax at source split
into its three components. Every amount is denominated in the received leg's own Instrument and
converts at the event date by the same rule as the leg (ADR-0017). The gross is derived — net plus
everything declared — never stored.

Only those three types may carry the declaration, and only with exactly one received leg, because
the amounts take their currency from it. A Quellensteuer and its country are recorded together or
not at all.

The ceiling a Quellensteuer is creditable up to is a **treaty limit** per source country,
configuration with a cited source. It keys on the country alone rather than on the year: a treaty
article does not move with the calendar, and a renegotiated treaty is a deliberate correction that
marks dependent reports stale.

## Considered Options

- **Gross in-leg plus out-legs for each tax.** Rejected: an out-leg of foreign cash is a disposal
  consuming a lot (ADR-0011), so every foreign dividend would mint and at once dispose of currency
  the Account never held, inventing §23 events — and the Account's history would show movements the
  broker's statement does not.
- **A new leg role for withheld amounts.** Rejected: every consumer reads legs by role, so each
  would need to learn to ignore the new one; the declaration touches only the producer that needs
  it.
- **Store the gross and derive the net.** Rejected: the net is the observed figure and the one the
  cash balance must reconcile to; a derived net could drift from the statement by a rounding.
- **Treaty limits in the per-year statutory store.** Rejected: that store's vocabulary is a closed,
  CHECK-pinned key list, and one key per country per year would be neither.

## Consequences

- Cash balances reconcile to the broker with no special case, and no engine but the capital-income
  producer knows withholding exists.
- The gross of an imported dividend is only as complete as its declaration: an import that carries
  no withholding columns records the net as the gross until the Admin states what was withheld.
- A distribution must name the fund that paid it, because the Teilfreistellung follows the payer;
  one that does not refuses at report time rather than entering its pot unexempted.
