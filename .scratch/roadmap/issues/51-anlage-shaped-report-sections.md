# 51 — Report sections shaped like the tax forms

**What to build:** The report is organised the way the German forms are, so transcription is mechanical rather than interpretive.

**Blocked by:** 46, 47, 24

**Status:** done

- [x] Sections map to the forms covering private sales and other income, capital income, and fund income not taxed at source
- [x] Each figure names the form line it corresponds to where the mapping is unambiguous, and says so plainly where it is not
- [x] Amounts withheld at source are shown separately from amounts still to declare
- [x] The report states a euro tax owed only where the statutory rate is fixed, and never where the marginal rate is unknown
- [x] Each category's balance for the year is shown so its form line can be filled directly
- [x] The appendix backs every headline figure, as established earlier
- [x] CSV and PDF exports both contain the same figures

## Comments

Implemented as a layer over the engines: `services/tax_forms.py` computes no tax — it takes the
year's §23, §22 and §20 figures and says where each belongs on Anlage SO, Anlage KAP and Anlage
KAP-INV. The sections are built at generation and frozen under `figures.forms` (ADR-0023), so
`GET /api/reports/{id}` answers them and both appendix exports restate them. There is no report
screen in the web app yet, so this ticket adds none.

How each criterion is held:

- **Sections map to the forms**: four sections in form order — Anlage SO Leistungen (§22 Nr. 3),
  Anlage SO private Veräußerungsgeschäfte (§23, a crypto block and "Andere Wirtschaftsgüter" for
  foreign cash), Anlage KAP, and Anlage KAP-INV for fund income no German Depot taxed.
- **Each figure names its form line, or says it cannot**: line numbers and printed labels are a
  table per Tax Year, read from the official 2024 and 2025 forms
  (`docs/research/tax-form-lines.md`). Every line states its mapping: `unambiguous`,
  `ambiguous` with every candidate line and the fact that would decide, or `unmapped` for a year
  whose form was never read.
- **Withheld apart from to declare**: every Anlage KAP line wears a side. Income a withholding
  Depot taxed stands on the withheld side (Zeile 7) with the tax taken (Zeilen 37 to 39);
  everything else is to declare, and a settled receipt never enters the to-declare lines.
- **Euro tax only where the rate is statutory**: Anlage KAP states the flat-rate tax from the
  §20 assessment; both Anlage SO sections state `stated: false` with the reason (ADR-0007).
- **Each category's balance**: the three pots' balances, the combined total, the allowance
  applied and the taxable remainder stand beside the Anlage KAP lines; each Anlage SO section
  shows its year total and what the Freigrenze leaves taxable.
- **The appendix backs every figure**: each appendix line names the form lines it feeds
  (`form_line_keys`), and the lines feeding one form line add up to its figure. A §20 row
  gained `gross_eur`, because the fund lines want the amount before Teilfreistellung, and the
  four withheld components, which the tax lines rest on. A loss line states the loss as its
  amount, so the rows behind it sum to that figure with the opposite sign.
- **CSV and PDF agree**: both still render the one `Appendix`; the PDF's line table now sizes
  its columns by their longest word, so the two new columns do not break a figure across lines.

Decisions worth recording:

- **Zeilen 18 and 19 are stated once.** The form splits income not taxed at source by whether
  the paying institution is domestic or foreign; the ledger does not record that, so the figure
  names both lines rather than guessing.
- **A §23 block holds one disposal.** With several, the block's figures are their total and are
  marked ambiguous, the Gewinn naming the further-disposals line too; the appendix is the
  separate schedule the form asks for.
- **2024 keeps Termingeschäfte apart, 2025 does not.** The 2024 form still prints Zeilen 21 and
  24, and its Zeilen 18/19 exclude futures losses by their own label; the 2025 form dropped both,
  so a futures loss is part of Zeilen 18/19 and restated on Zeile 22.
- **The tax is stated before crediting what was withheld.** Ticket 47 left the netting to this
  ticket: the withheld German tax and the creditable Quellensteuer stand on their own lines and
  are not subtracted — the credit is the Finanzamt's to apply.
- **`Section20Year` gained `disposals`**, the year's securities disposals as their producer
  stated them, because the event shape deliberately carries neither Depot nor Instrument and the
  layout turns on both.
- **Not mapped here**: Vorabpauschale lines on Anlage KAP-INV wait for ticket 53, and the
  Sparerpauschbetrag lines (Zeilen 16 and 17) wait until allowance consumed at source is a
  figure rather than a standing zero.
- Left unverified by the form research, and stated as such in the notes the lines carry: whether
  Zeile 19 is entered gross of foreign tax (the report states gross), and how a Steuerbescheinigung
  states fund income on Zeile 7 (the line says to compare with the certificate).
- **Zeilen 18/19 total across the pots.** The form asks for one net figure over all capital
  income not taxed at source; the total is confined to those lines and feeds no computation
  (ADR-0023).
- **A year awaiting a valuation states no capital-income line.** The Anlage KAP and KAP-INV
  sections then carry a sentence naming what the year waits on, as the engine states no balance
  around a missing figure.
- **An unmapped year borrows the nearest mapped year's labels**, and with them that form's
  treatment of Termingeschäfte, rather than always the newest.
- Reports generated before this ticket carry no `forms` and must be regenerated.
- Post-review fixes (two-axis review): labels are now the forms' printed wording per year, where
  they had been shortened; Zeile 7 is marked ambiguous, since the form wants the certificate's
  figure; creditable Quellensteuer is split exactly between Zeilen 40 and 41 by the receiving
  Depot, through the engine's one rule (`section20.creditable_eur`), instead of one ambiguous
  line; the appendix gained the withheld columns so the tax lines are backed; the export column
  was renamed from `form_lines` to `form_line_keys`; the fund-type list is no longer duplicated.
- Left as is from the review: the category balances carry no form line (they are after
  Teilfreistellung and span both sides, so they check the lines rather than fill one); German
  tax withheld on a receipt at a Depot that itself withholds nothing still stands on the withheld
  side, because it was withheld; `Status: done` follows tickets 46 and 47.

**Update (2026-10-04).** The web has a report screen now: ticket 58 added a Reports section to the
multi-year overview.
