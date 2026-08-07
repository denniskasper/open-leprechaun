# The report states taxable amounts, not tax owed — except where the rate is statutory

## Status

accepted — carried from v1's ADR-0007

## Context

For private sales and other income the applicable rate is the taxpayer's personal marginal
income-tax rate, which depends on their total yearly income and is unknown to a self-hosted tool.
Only capital income carries a fixed statutory rate the tool can apply.

## Decision

Compute and present the taxable **amount** for each regime. State a euro tax owed only where the
rate is statutorily fixed. Where a personal-rate comparison might produce a better outcome, note
that it may apply — do not compute it. The report is a draft aid to be verified with a
Steuerberater, and says so.

## Consequences

- Do not add a total-tax-owed figure for the personal-rate regimes without first collecting the
  Admin's marginal rate. The deliberate output is the taxable base.
- Statutory constants must stay year-pinned and auditable, because the law shifts and an undated
  constant is a latent correctness bug. This is why every such value is configuration with a cited
  source rather than a literal in logic.
