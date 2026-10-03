# Form lines are a year-keyed table in code, frozen with the report

## Status

accepted

## Context

The report is laid out like the forms it is transcribed onto — Anlage SO, Anlage KAP, Anlage
KAP-INV — and each figure names the Zeile it belongs on. Those line numbers are not stable: the
Anlage SO blocks sit four lines later in 2025 than in 2024, and the 2025 Anlage KAP dropped the
separate Termingeschäfte lines after the JStG 2024. A number carried over from another year is
wrong in a way nobody notices until the return is rejected or, worse, accepted.

The statutory store (ticket 09) is where per-year law normally lives, but it holds decimals under
a closed, CHECK-pinned key list. A form layout is neither a decimal nor a value the Admin has any
business tuning: it is a transcription of a printed document.

## Decision

Each mapped Tax Year has its own table of form fields — line number and printed label — in
`services/tax_forms.py`, read from that year's official form and cited in
`docs/research/tax-form-lines.md`. No year's numbers are inferred from another's. A year without a
table still lays the report out by form and field, borrows the nearest mapped year's labels, and
says plainly that the line number is not mapped.

Every figure states how sure its mapping is: **unambiguous**, **ambiguous** — the form offers
several lines and the ledger holds no fact that decides, such as whether a paying institution is
domestic — or **unmapped**. An ambiguous figure is stated once with every candidate line and the
fact that would decide; it is never split by guess.

The sections are built when the report is generated and frozen with its figures. Which block a
figure belongs in depends on what an Instrument is and whether a Depot withholds — facts that can
change after generation — so deriving the layout on read would let a final report's form lines
move underneath it.

Anlage KAP's lines for income not taxed at source ask for one total across everything, net of its
losses. That is a sum across the **Verlustverrechnungstöpfe**, which the glossary forbids "at any
point" — so it is confined to those form lines, which restate the share and loss parts beside the
total exactly as the form does. The category balances, the offsetting and the tax stay per pot
(ADR-0013); the form total feeds no computation.

The form sections state a euro tax only for capital income (ADR-0007), and state it before
crediting what was withheld at source: the withheld German tax and the creditable Quellensteuer
stand on their own lines, and the netting is the Finanzamt's.

## Considered Options

- **Line numbers in the statutory store.** Rejected: not decimals, not Admin-tunable, and one key
  per field per year would break the closed vocabulary — the same reasoning as ADR-0022.
- **Form and field label only, no numbers.** Rejected: transcription stays interpretive, which is
  what the report exists to remove.
- **Derive the sections on read from the frozen figures.** Rejected: the classification inputs
  are live, so a final report could change.

## Consequences

- A new Tax Year needs its forms read and a table added before its report names line numbers;
  until then the report is usable and honest about the gap.
- A report generated before this decision carries no form sections and must be regenerated, as
  with every earlier change to the frozen shape.
- Fund income not taxed at source is stated before Teilfreistellung on Anlage KAP-INV, because
  the form asks for it that way; the category balances beside it stay after Teilfreistellung.
