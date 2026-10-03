# German tax form line numbers: Anlage SO, KAP, KAP-INV (2024 and 2025)

Researched 2026-10-03. Every line number below was read separately for each
year from the official form in the Formular-Management-System (FMS) of the
Bundesfinanzverwaltung and its official "Anleitung". Nothing was carried over
from one year to the other. No secondary source was needed for any table entry.

## Sources

All sources are primary (Bundesfinanzverwaltung, `formulare-bfinv.de`).

How they were read: the FMS serves each form as an online HTML form (the "NET"
variant) after a browser-capability handshake. The stable entry URL is the
`invoke.do?id=…` link, which the Landesamt für Steuern Niedersachsen publishes
on its form pages. The Anleitung is a PDF linked from inside the form; its URL
is session-bound (`/ffw/resources/<session>/form/<file>.pdf`), so only the file
name is stable.

| Form | Year | What | URL / file | Revision stamp |
|---|---|---|---|---|
| Anlage SO | 2024 | form (FMS online form, 3 pages) | https://www.formulare-bfinv.de/ffw/action/invoke.do?id=034029_24 | `2024AnlSO131NET`–`133NET`, September 2024 |
| Anlage SO | 2024 | Anleitung (PDF, 3 pages) | `Anltg_SO_24.pdf`, linked from the form above | September 2024 |
| Anlage SO | 2025 | form (FMS online form, 3 pages) | https://www.formulare-bfinv.de/ffw/action/invoke.do?id=034029_25 | `2025AnlSO131NET`–`133NET`, September 2025 |
| Anlage SO | 2025 | Anleitung (PDF, 4 pages) | `Anltg_SO_25.pdf`, linked from the form above | September 2025 |
| Anlage KAP | 2024 | form (FMS online form, 3 pages) | https://www.formulare-bfinv.de/ffw/action/invoke.do?id=034024_24 | `2024AnlKAP051NET`–`053NET`, September 2024 |
| Anlage KAP | 2024 | Anleitung (PDF, 6 pages) | `Anltg_KAP_24.pdf`, linked from the form above | September 2024 |
| Anlage KAP | 2025 | form (FMS online form, 3 pages) | https://www.formulare-bfinv.de/ffw/action/invoke.do?id=034024_25 | `2025AnlKAP051NET`–`053NET`, Oktober 2025 |
| Anlage KAP | 2025 | Anleitung (PDF, 6 pages) | `Anltg_KAP_25.pdf`, linked from the form above | September 2025 |
| Anlage KAP-INV | 2024 | form (FMS online form, 3 pages) | https://www.formulare-bfinv.de/ffw/action/invoke.do?id=035004_24 | `2024AnlKAP-INV361NET`–`363NET`, September 2024 |
| Anlage KAP-INV | 2024 | Anleitung (PDF, 4 pages) | `Anltg_KAP_INV_24.pdf`, linked from the form above | September 2024 |
| Anlage KAP-INV | 2025 | form (FMS online form, 3 pages) | https://www.formulare-bfinv.de/ffw/action/invoke.do?id=035004_25 | `2025AnlKAP-INV361NET`–`363NET`, September 2025 |
| Anlage KAP-INV | 2025 | Anleitung (PDF, 4 pages) | `Anltg_KAP_INV_25.pdf`, linked from the form above | September 2025 |

Index pages used only to find the FMS form IDs (official, Land Niedersachsen):

- https://lstn.niedersachsen.de/startseite/steuer/steuervordrucke/einkommensteuer/2024/einkommensteuer-2024-234827.html
- https://lstn.niedersachsen.de/startseite/steuer/steuervordrucke/einkommensteuer/2025/einkommensteuer-2025-247400.html

Limits of the method:

- The form was read as the FMS HTML form, not as a rendered print PDF. Line
  numbers come from the form's own per-field descriptions ("Zeile 44. …") and
  the printed line-number column, which agree. Printed labels were taken from
  the form's text layer; where a label wraps over several lines it was rejoined
  and the end-of-line hyphen removed. Treat labels as verbatim in wording, not
  in line breaks.
- The Anleitung PDFs were read through text extraction (multi-column layout),
  not visually. Quotes below were rejoined across line breaks the same way.

## Anlage SO

Both years have two amount columns for §22 Nr. 3 and for the §23 allocation
lines: left "Steuerpflichtige Person / Ehemann / Person A" (2024 adds
"/ Gemeinschaft / Gesellschaft"), right "Ehefrau / Person B". One Anlage SO per
jointly assessed couple. All 2025 lines in the blocks below sit four lines
later than in 2024, and "Einheiten virtueller Währungen und / oder sonstige
Token" was renamed "Kryptowerte".

### §22 Nr. 3 EStG "Leistungen"

| Field | 2024 Zeile | 2024 printed label | 2025 Zeile | 2025 printed label | Verified from |
|---|---|---|---|---|---|
| Block heading | – | "Leistungen" / "Angaben zu Tätigkeiten im Zusammenhang mit Einheiten virtueller Währungen und / oder sonstigen Token" | – | "Leistungen" / "Angaben zu Tätigkeiten im Zusammenhang mit Kryptowerten" | primary |
| Crypto activity yes/no (per person) | 10 | "Haben Sie Einkünfte aus Mining, Forging, Staking, Lending und / oder der Teilnahme an Airdrops oder ähnlichen Vorgängen erzielt?" (1 = Ja) | 14 | "Haben Sie Einkünfte aus Mining, Forging, (passivem) Staking, Lending und / oder der Teilnahme an Airdrops oder ähnlichen Vorgängen erzielt?" (1 = Ja) | primary |
| Einnahmen, crypto-related (per person) | 11 | "Einnahmen im Zusammenhang mit Einheiten virtueller Währungen und / oder sonstigen Token:" | 15 | "Einnahmen im Zusammenhang mit Kryptowerten:" | primary |
| Einnahmen, other Leistungen (description + amount per person) | 12, 13 | "Angaben zu weiteren Leistungen" / "Einnahmen aus:" | 16, 17 | "Angaben zu weiteren Leistungen" / "Einnahmen aus:" | primary |
| Sum of Einnahmen (per person) | 14 | "Summe der Einnahmen laut den Zeilen 11 bis 13" | 18 | "Summe der Einnahmen laut den Zeilen 15 bis 17" | primary |
| Werbungskosten (per person) | 15 | "Werbungskosten zu den Einnahmen laut den Zeilen 11 bis 13" | 19 | "Werbungskosten zu den Einnahmen laut den Zeilen 15 bis 17" | primary |
| Einkünfte (per person) | 16 | "Einkünfte" | 20 | "Einkünfte" | primary |
| Wirtschafts-Identifikationsnummer | 17 | "Wirtschafts-Identifikationsnummer zu den Zeilen 12 und 13" | 21 | "Wirtschafts-Identifikationsnummer zu den Zeilen 16 und 17" | primary |
| Waiver of loss carryback (per person) | 18 | "Ich beantrage von einem Verlustrücktrag nach § 10d EStG in das Jahr 2023 abzusehen." (1 = Ja) | 22 | "Ich beantrage von einem Verlustrücktrag nach § 10d EStG in das Jahr 2024 abzusehen." (1 = Ja) | primary |

### §23 EStG — crypto block

Block heading: 2024 "Private Veräußerungsgeschäfte" / "Einheiten virtueller
Währungen und / oder sonstige Token"; 2025 "Private Veräußerungsgeschäfte" /
"Kryptowerte". The block holds exactly one disposal (single amount column);
further disposals go to the "weitere Veräußerungen" line with a separate
schedule.

| Field | 2024 Zeile | 2024 printed label | 2025 Zeile | 2025 printed label | Verified from |
|---|---|---|---|---|---|
| Yes/no question (per person) | 41 | "Haben Sie Einkünfte aus der Veräußerung von Einheiten virtueller Währungen und / oder sonstigen Token erzielt?" (1 = Ja) | 45 | "Haben Sie Einkünfte aus der Veräußerung von Kryptowerten erzielt?" (1 = Ja) | primary |
| Description | 42 | "Bezeichnung" | 46 | "Bezeichnung" | primary |
| Acquisition date / disposal date (two fields on one line) | 43 | "Zeitpunkt der Anschaffung (z. B. der auf der verwendeten Handelsplattform aufgezeichnete Zeitpunkt)" / "Zeitpunkt der Veräußerung (z. B. der auf der verwendeten Handelsplattform aufgezeichnete Zeitpunkt)" | 47 | same wording | primary |
| Veräußerungspreis | 44 | "Veräußerungspreis oder an dessen Stelle tretender Wert (z. B. gemeiner Wert)" | 48 | same wording | primary |
| Anschaffungskosten (subtracted) | 45 | "Anschaffungskosten oder an deren Stelle tretender Wert (z. B. Teilwert, gemeiner Wert)" | 49 | same wording | primary |
| Werbungskosten (subtracted) | 46 | "Werbungskosten im Zusammenhang mit dem Veräußerungsgeschäft" | 50 | same wording | primary |
| Gewinn / Verlust (block result) | 47 | "Gewinn / Verlust (zu übertragen nach Zeile 54)" | 51 | "Gewinn / Verlust (zu übertragen nach Zeile 58)" | primary |
| Note under the block | – | "– Erläutern Sie bitte die Ermittlung des Gewinns / Verlusts zusätzlich in einer gesonderten Aufstellung. –" | – | same wording | primary |

### §23 EStG — "Andere Wirtschaftsgüter" (foreign-currency cash goes here)

Block heading both years: "Andere Wirtschaftsgüter" / "– Veräußerungen von
Gegenständen des täglichen Gebrauchs sind ausgenommen. –".

| Field | 2024 Zeile | 2024 printed label | 2025 Zeile | 2025 printed label | Verified from |
|---|---|---|---|---|---|
| Description | 48 | "Art des Wirtschaftsguts" | 52 | "Art des Wirtschaftsguts" | primary |
| Acquisition date / disposal date | 49 | "Zeitpunkt der Anschaffung (z. B. Datum des Kaufvertrags)" / "Zeitpunkt der Veräußerung (z. B. Datum des Kaufvertrags)" | 53 | same wording | primary |
| Veräußerungspreis | 50 | "Veräußerungspreis oder an dessen Stelle tretender Wert (z. B. gemeiner Wert)" | 54 | same wording | primary |
| Anschaffungskosten (subtracted) | 51 | "Anschaffungskosten (ggf. gemindert um Absetzung für Abnutzung) oder an deren Stelle tretender Wert (z. B. Teilwert, gemeiner Wert)" | 55 | same wording | primary |
| Werbungskosten (subtracted) | 52 | "Werbungskosten im Zusammenhang mit dem Veräußerungsgeschäft" | 56 | same wording | primary |
| Gewinn / Verlust (block result) | 53 | "Gewinn / Verlust (zu übertragen nach Zeile 54)" | 57 | "Gewinn / Verlust (zu übertragen nach Zeile 58)" | primary |

### §23 EStG — allocation, further disposals, carryback

| Field | 2024 Zeile | 2024 printed label | 2025 Zeile | 2025 printed label | Verified from |
|---|---|---|---|---|---|
| Allocation of both block results (per person) | 54 | "Zurechnung der Beträge aus den Zeilen 47 und 53" | 58 | "Zurechnung der Beträge aus den Zeilen 51 und 57" | primary |
| Further disposals, crypto and other assets together (per person) | 55 | "Gewinne / Verluste aus weiteren Veräußerungen von Einheiten virtueller Währungen und sonstigen Token sowie anderen Wirtschaftsgütern (laut gesonderter Aufstellung)" | 59 | "Gewinne / Verluste aus weiteren Veräußerungen von Kryptowerten sowie anderen Wirtschaftsgütern (laut gesonderter Aufstellung)" | primary |
| Waiver of loss carryback for §23 (per person) | 62 | "Ich beantrage von einem Verlustrücktrag nach § 10d EStG in das Jahr 2023 abzusehen." (1 = Ja) | 66 | "Ich beantrage von einem Verlustrücktrag nach § 10d EStG in das Jahr 2024 abzusehen." (1 = Ja) | primary |
| Grand total of all §23 gains/losses | none | no such line on the form | none | no such line on the form | primary (absence) |
| Freigrenze line | none | no such line on the form; Freigrenze appears only in the Anleitung | none | same | primary (absence) |

For orientation (not requested): real estate is lines 30–40 in 2024 and 34–44
in 2025; shares in jointly determined income are lines 56–61 in 2024 and 60–65
in 2025.

## Anlage KAP

One Anlage KAP per person (no spouse columns). Lines 7–15 have two amount
columns: "Beträge laut Steuerbescheinigung(en)" and "korrigierte Beträge (laut
gesonderter Aufstellung)". Lines 18–26a have a single column.

### Requests

| Field | 2024 Zeile | 2024 printed label | 2025 Zeile | 2025 printed label | Verified from |
|---|---|---|---|---|---|
| Günstigerprüfung | 4 | "Ich beantrage die Günstigerprüfung für sämtliche Kapitalerträge. (Bei Zusammenveranlagung: Die Anlage KAP meines Ehegatten / Lebenspartners ist beigefügt.)" (1 = Ja) | 4 | same wording | primary |
| Überprüfung des Steuereinbehalts | 5 | "Ich beantrage eine Überprüfung des Steuereinbehalts für bestimmte Kapitalerträge." (1 = Ja) | 5 | same wording | primary |
| Kirchensteuer declaration | 6 | "Ich bin kirchensteuerpflichtig und habe Kapitalerträge erzielt, von denen Kapitalertragsteuer, aber keine Kirchensteuer einbehalten wurde." (1 = Ja) | 6 | same wording | primary |

### "Kapitalerträge, die dem inländischen Steuerabzug unterlegen haben"

| Field | 2024 Zeile | 2024 printed label | 2025 Zeile | 2025 printed label | Verified from |
|---|---|---|---|---|---|
| Kapitalerträge | 7 | "Kapitalerträge" | 7 | "Kapitalerträge" | primary |
| Included share gains | 8 | "In Zeile 7 enthaltene Gewinne aus Aktienveräußerungen" | 8 | same wording | primary |
| Included Stillhalterprämien / Termingeschäfte gains | 9 | "In Zeile 7 enthaltene Einkünfte aus Stillhalterprämien und Gewinne aus Termingeschäften" | 9 | same wording | primary |
| Included gains on grandfathered fund units | 10 | "In Zeile 7 enthaltene Gewinne aus der Veräußerung bestandsgeschützter Alt-Anteile i. S. d. § 56 Abs. 6 Satz 1 Nr. 2 InvStG" | 10 | same wording | primary |
| Included Ersatzbemessungsgrundlage | 11 | "In Zeile 7 enthaltene Ersatzbemessungsgrundlage" | 11 | same wording | primary |
| Losses excluding shares | 12 | "Nicht ausgeglichene Verluste ohne Verluste aus der Veräußerung von Aktien" | 12 | same wording | primary |
| Losses from shares | 13 | "Nicht ausgeglichene Verluste aus der Veräußerung von Aktien" | 13 | same wording | primary |
| Losses from Termingeschäfte | 14 | "Verluste aus Termingeschäften" | 14 | "Verluste aus Termingeschäften" (line still present, see notes) | primary |
| Losses from uncollectible/worthless assets | 15 | "Verluste aus der ganzen oder teilweisen Uneinbringlichkeit einer Kapitalforderung, Ausbuchung, Übertragung wertlos gewordener Wirtschaftsgüter i. S. d. § 20 Abs. 1 EStG oder aus einem sonstigen Ausfall von Wirtschaftsgütern i. S. d. § 20 Abs. 1 EStG" | 15 | same wording (line still present, see notes) | primary |
| Sparer-Pauschbetrag used on declared income | 16 | "In Anspruch genommener Sparer-Pauschbetrag, der auf die in den Zeilen 7 bis 15, 30 und 33 erklärten Kapitalerträge entfällt (ggf. „0“)" | 16 | same wording | primary |
| Sparer-Pauschbetrag used on income not declared in Anlage KAP | 17 | "Bei Eintragungen in den Zeilen 7 bis 15, 18 bis 27, 30, 33, 52 und 54 der Anlage KAP, in den Zeilen 8 bis 30, 33 und 34 der Anlage KAP-BET sowie in der Anlage KAP-INV: In Anspruch genommener Sparer-Pauschbetrag, der auf die in der Anlage KAP nicht erklärten Kapitalerträge entfällt (ggf. „0“)" | 17 | same, except the KAP-BET reference reads "in den Zeilen 8 bis 24, 27 und 28 der Anlage KAP-BET" | primary |

### "Kapitalerträge, die nicht dem inländischen Steuerabzug unterlegen haben – ohne Investmenterträge laut Anlage KAP-INV –"

| Field | 2024 Zeile | 2024 printed label | 2025 Zeile | 2025 printed label | Verified from |
|---|---|---|---|---|---|
| Domestic income | 18 | "Inländische Kapitalerträge (ohne Beträge laut den Zeilen 24 bis 26a)" | 18 | "Inländische Kapitalerträge (ohne Beträge laut den Zeilen 26 und 26a)" | primary |
| Foreign income | 19 | "Ausländische Kapitalerträge (ohne Beträge laut den Zeilen 24, 25, 26a und 52)" | 19 | "Ausländische Kapitalerträge (ohne Beträge laut den Zeilen 26a und 52)" | primary |
| Included share gains | 20 | "In den Zeilen 18 und 19 enthaltene Gewinne aus Aktienveräußerungen i. S. d. § 20 Abs. 2 Satz 1 Nr. 1 EStG" | 20 | same wording | primary |
| Included Stillhalterprämien / Termingeschäfte gains | 21 | "In den Zeilen 18 und 19 enthaltene Einkünfte aus Stillhalterprämien und Gewinne aus Termingeschäften" | removed | printed "21 frei" | primary |
| Included losses excluding shares | 22 | "In den Zeilen 18 und 19 enthaltene Verluste ohne Verluste aus der Veräußerung von Aktien" | 22 | same wording | primary |
| Included losses from shares | 23 | "In den Zeilen 18 und 19 enthaltene Verluste aus der Veräußerung von Aktien i. S. d. § 20 Abs. 2 Satz 1 Nr. 1 EStG" | 23 | same wording | primary |
| Losses from Termingeschäfte | 24 | "Verluste aus Termingeschäften" | removed | printed "24 und 25 frei" | primary |
| Losses from uncollectible/worthless assets | 25 | "Verluste aus der ganzen oder teilweisen Uneinbringlichkeit einer Kapitalforderung, Ausbuchung, Übertragung wertlos gewordener Wirtschaftsgüter i. S. d. § 20 Abs. 1 EStG oder aus einem sonstigen Ausfall von Wirtschaftsgütern i. S. d. § 20 Abs. 1 EStG" | removed | printed "24 und 25 frei" | primary |
| Interest paid by the Finanzamt | 26 | "Zinsen, die vom Finanzamt für Steuererstattungen gezahlt wurden (ohne an das Finanzamt zurückgezahlte Zinsen für Steuererstattungen) – Bitte Anleitung beachten. –" | 26 | same wording | primary |
| Litigation / default interest | 26a | "Prozess- und Verzugszinsen" | 26a | "Prozess- und Verzugszinsen" | primary |

### "Steuerabzugsbeträge" / "Anzurechnende Steuern"

Amounts in EUR and Ct, column "laut Bescheinigung(en)". Block heading 2024:
"Steuerabzugsbeträge zu Erträgen in den Zeilen 7 bis 25 und zu
Investmenterträgen laut Anlage KAP-INV"; 2025: "… in den Zeilen 7 bis 23 und
zu Investmenterträgen laut Anlage KAP-INV".

| Field | 2024 Zeile | 2024 printed label | 2025 Zeile | 2025 printed label | Verified from |
|---|---|---|---|---|---|
| Kapitalertragsteuer | 37 | "Kapitalertragsteuer" | 37 | "Kapitalertragsteuer" | primary |
| Solidaritätszuschlag | 38 | "Solidaritätszuschlag" | 38 | "Solidaritätszuschlag" | primary |
| Kirchensteuer | 39 | "Kirchensteuer zur Kapitalertragsteuer" | 39 | "Kirchensteuer zur Kapitalertragsteuer" | primary |
| Foreign tax already credited | 40 | "Angerechnete ausländische Steuern" | 40 | "Angerechnete ausländische Steuern" | primary |
| Foreign tax creditable, not yet credited | 41 | "Anrechenbare noch nicht angerechnete ausländische Steuern" | 41 | same wording | primary |
| Fictitious withholding tax | 42 | "Fiktive ausländische Quellensteuer (nicht in den Zeilen 40 und / oder 41 enthalten)" | 42 | same wording | primary |
| KapESt / SolZ / KiSt on tariff-taxed income and other income types | 43 / 44 / 45 | block "Anzurechnende Steuern zu Erträgen in den Zeilen 28 bis 34 sowie aus anderen Einkunftsarten": "Kapitalertragsteuer" / "Solidaritätszuschlag" / "Kirchensteuer zur Kapitalertragsteuer" | 43 / 44 / 45 | same wording | primary |
| Tax amount owed | none | no such line; the form ends at line 55 (Steuerstundungsmodelle) | none | same | primary (absence) |

## Anlage KAP-INV

One Anlage KAP-INV per person, with a running number ("lfd. Nr. der Anlage")
because the calculation pages hold only two funds each. Line numbers are
identical in 2024 and 2025; only year references and the Basisertrag rate
changed. Section headings: "Investmenterträge, die nicht dem inländischen
Steuerabzug unterlegen haben" / "Laufende Erträge aus Investmentanteilen, die
nicht dem inländischen Steuerabzug unterlegen haben (z. B. bei im Ausland
verwahrten Investmentanteilen)".

### Ausschüttungen

Sub-heading both years: "Ausschüttungen nach § 2 Abs. 11 InvStG (einschließlich
des ausländischen Steuerabzugs auf den Kapitalertrag) aus".

| Field | 2024 Zeile | 2024 printed label | 2025 Zeile | 2025 printed label | Verified from |
|---|---|---|---|---|---|
| Aktienfonds | 4 | "– Aktienfonds i. S. d. § 2 Abs. 6 InvStG (vor Teilfreistellung)" | 4 | same wording | primary |
| Mischfonds | 5 | "– Mischfonds i. S. d. § 2 Abs. 7 InvStG (vor Teilfreistellung)" | 5 | same wording | primary |
| Immobilienfonds | 6 | "– Immobilienfonds i. S. d. § 2 Abs. 9 Satz 1 InvStG (vor Teilfreistellung und ohne Beträge laut Zeile 7)" | 6 | same wording | primary |
| Auslands-Immobilienfonds | 7 | "– Auslands-Immobilienfonds i. S. d. § 2 Abs. 9 Satz 2 InvStG (vor Teilfreistellung)" | 7 | same wording | primary |
| Sonstige Investmentfonds | 8 | "– sonstigen Investmentfonds" | 8 | same wording | primary |

### Vorabpauschalen

Sub-heading: "Vorabpauschalen nach § 18 InvStG aus"; 2024 note "– ggf. Übertrag
aus Zeile 45 oder laut Aufstellung des ausländischen Kreditinstituts –", 2025
note "– Übertrag aus Zeile 45 oder laut Aufstellung des ausländischen
Kreditinstituts –".

| Field | 2024 Zeile | 2024 printed label | 2025 Zeile | 2025 printed label | Verified from |
|---|---|---|---|---|---|
| Aktienfonds | 9 | "– Aktienfonds i. S. d. § 2 Abs. 6 InvStG (vor Teilfreistellung)" | 9 | same wording | primary |
| Mischfonds | 10 | "– Mischfonds i. S. d. § 2 Abs. 7 InvStG (vor Teilfreistellung)" | 10 | same wording | primary |
| Immobilienfonds | 11 | "– Immobilienfonds i. S. d. § 2 Abs. 9 Satz 1 InvStG (vor Teilfreistellung und ohne Beträge laut Zeile 12)" | 11 | same wording | primary |
| Auslands-Immobilienfonds | 12 | "– Auslands-Immobilienfonds i. S. d. § 2 Abs. 9 Satz 2 InvStG (vor Teilfreistellung)" | 12 | same wording | primary |
| Sonstige Investmentfonds | 13 | "– sonstigen Investmentfonds" | 13 | same wording | primary |

### Veräußerungsgewinne / -verluste (summary lines, first Anlage KAP-INV)

Heading: "Gewinne und Verluste aus der Veräußerung von Investmentanteilen, die
nicht dem inländischen Steuerabzug unterlegen haben (z. B. bei im Ausland
verwahrten Investmentanteilen)" with the note "Übertrag aus den Zeilen 54, 55
und / oder 56 oder laut Aufstellung des ausländischen Kreditinstituts" (2024
prefixes "ggf.").

| Field | 2024 Zeile | 2024 printed label | 2025 Zeile | 2025 printed label | Verified from |
|---|---|---|---|---|---|
| Aktienfonds, gain/loss | 14 | "Aktienfonds i. S. d. § 2 Abs. 6 InvStG (vor Teilfreistellung)" | 14 | same wording | primary |
| … of which grandfathered units | 15 | "In Zeile 14 enthaltene Gewinne aus der Veräußerung bestandsgeschützter Alt-Anteile i. S. d. § 56 Abs. 6 Satz 1 Nr. 2 InvStG (vor Teilfreistellung)" | 15 | same wording | primary |
| … fictitious disposal of non-grandfathered old units | 16 | "Gewinne und Verluste aus der fiktiven Veräußerung von nicht bestandsgeschützten Alt-Anteilen i. S. d. § 56 Abs. 2 i. V. m. Abs. 3 Satz 1 InvStG (nicht in Zeile 14 enthalten)" | 16 | same wording | primary |
| Mischfonds, gain/loss | 17 | "Mischfonds i. S. d. § 2 Abs. 7 InvStG (vor Teilfreistellung)" | 17 | same wording | primary |
| … grandfathered / fictitious | 18 / 19 | as 15 / 16, referring to Zeile 17 (form prints "In Zeile 17 enthalte Gewinne …", sic) | 18 / 19 | same wording | primary |
| Immobilienfonds, gain/loss | 20 | "Immobilienfonds i. S. d. § 2 Abs. 9 Satz 1 InvStG (vor Teilfreistellung und ohne Beträge laut Zeile 23)" | 20 | same wording | primary |
| … grandfathered / fictitious | 21 / 22 | as 15 / 16, referring to Zeile 20 | 21 / 22 | same wording | primary |
| Auslands-Immobilienfonds, gain/loss | 23 | "Auslands-Immobilienfonds i. S. d. § 2 Abs. 9 Satz 2 InvStG (vor Teilfreistellung)" | 23 | same wording | primary |
| … grandfathered / fictitious | 24 / 25 | as 15 / 16, referring to Zeile 23 | 24 / 25 | same wording | primary |
| Sonstige Investmentfonds, gain/loss | 26 | "Sonstige Investmentfonds" | 26 | same wording | primary |
| … grandfathered / fictitious | 27 / 28 | as 15 / 16, referring to Zeile 26, without "(vor Teilfreistellung)" | 27 / 28 | same wording | primary |
| Zwischengewinne (InvStG 2004) | 29 | "Bei Veräußerung von vor dem 1.1.2018 angeschafften Investmentanteilen: Zwischengewinne aus fiktiven Veräußerungen zum 31.12.2017 nach § 56 Abs. 2 i. V. m. Abs. 3 InvStG" | 29 | same wording | primary |

### Calculation blocks (two fund columns per page: "1. Investmentfonds", "2. Investmentfonds")

"Ermittlung der Vorabpauschalen zu den Zeilen 9 bis 13":

| Field | 2024 Zeile | 2024 printed label | 2025 Zeile | 2025 printed label | Verified from |
|---|---|---|---|---|---|
| ISIN | 30 | "ISIN" | 30 | "ISIN" | primary |
| Fund name | 31 | "Fondsbezeichnung" | 31 | "Fondsbezeichnung" | primary |
| Fund type code | 32 | "Art des Investmentfonds" (1 = Aktienfonds, 2 = Mischfonds, 3 = Immobilienfonds, 4 = Auslands-Immobilienfonds, 5 = sonstiger Investmentfonds) | 32 | same wording | primary |
| Price at start of year | 33 | "Rücknahme-, Börsen- oder Marktpreis für einen Investmentanteil zu Beginn des Kalenderjahres 2023" | 33 | "… zu Beginn des Kalenderjahres 2024" | primary |
| Basisertrag | 34 | "Basisertrag (Zeile 33 × 1,785 %)" | 34 | "Basisertrag (Zeile 33 × 1,603 %)" | primary |
| Last redemption price | 35 | "Letzter Rücknahmepreis 2023" | 35 | "Letzter Rücknahmepreis 2024" | primary |
| Less first redemption price | 36 | "abzüglich erster Rücknahmepreis 2023 (laut Zeile 33)" | 36 | "abzüglich erster Rücknahmepreis 2024 (laut Zeile 33)" | primary |
| Plus distributions | 37 | "zuzüglich Ausschüttungen 2023" | 37 | "zuzüglich Ausschüttungen 2024" | primary |
| Mehrbetrag | 38 | "Mehrbetrag" | 38 | "Mehrbetrag" | primary |
| Lower of Basisertrag / Mehrbetrag | 39 | "Niedrigerer Wert aus Zeile 34 (Basisertrag) oder Zeile 38 (Mehrbetrag) (wenn Wert negativ, in Zeile 43 „0“ eintragen)" | 39 | same wording | primary |
| Less distributions | 40 | "abzüglich Ausschüttungen 2023" | 40 | "abzüglich Ausschüttungen 2024" | primary |
| Intermediate result | 41 | "Zwischenergebnis Zeile 39 abzüglich Zeile 40 (wenn Wert negativ, in Zeile 43 „0“ eintragen)" | 41 | same wording | primary |
| Pro-rata reduction | 42 | "bei unterjährigem Erwerb im Jahr 2023: Kürzung Wert laut Zeile 41 um 1/12 für jeden vollen Monat vor Erwerb" | 42 | "bei unterjährigem Erwerb im Jahr 2024: …" | primary |
| Intermediate result | 43 | "Zwischenergebnis (Zeile 41 abzüglich Zeile 42)" | 43 | same wording | primary |
| Number of units | 44 | "Anzahl der Anteile (mit Nachkommastellen)" | 44 | same wording | primary |
| Vorabpauschale | 45 | "Vorabpauschale (Zeile 43 x Zeile 44)" | 45 | same wording | primary |

"Ermittlung der Gewinne und Verluste aus der Veräußerung von Investmentanteilen
zu den Zeilen 14 bis 28":

| Field | 2024 Zeile | 2024 printed label | 2025 Zeile | 2025 printed label | Verified from |
|---|---|---|---|---|---|
| ISIN | 46 | "ISIN (Internationale Wertpapiernummer)" | 46 | same wording | primary |
| Fund name | 47 | "Fondsbezeichnung" | 47 | same wording | primary |
| Fund type code | 48 | "Art des Investmentfonds" (codes 1–5 as line 32) | 48 | same wording | primary |
| Units sold | 49 | "Anzahl der veräußerten Anteile (mit Nachkommastellen)" | 49 | same wording | primary |
| Veräußerungspreis | 50 | "Veräußerungspreis" | 50 | same wording | primary |
| Anschaffungskosten | 51 | "abzüglich Anschaffungskosten (bei Anschaffung vor dem 1.1.2018: fiktive Anschaffungskosten i. S. d. § 56 Abs. 2 InvStG)" | 51 | same wording | primary |
| Veräußerungskosten | 52 | "abzüglich Veräußerungskosten" | 52 | same wording | primary |
| Vorabpauschalen already taxed | 53 | "abzüglich während Besitzzeit angesetzter Vorabpauschalen (vor Teilfreistellung)" | 53 | same wording | primary |
| Gain / loss | 54 | "Veräußerungsgewinn / -verlust (Zeile 50 abzüglich Zeile 51 bis 53)" | 54 | same wording | primary |
| Units acquired before 2009 | 55 | "bei Anschaffung vor dem 1.1.2009: Wert laut Zeile 54" | 55 | same wording | primary |
| Units acquired 2009–2017 | 56 | "bei Anschaffung nach dem 31.12.2008 und vor dem 1.1.2018: fiktiver Veräußerungsgewinn zum 31.12.2017" | 56 | same wording | primary |

Transfer rules printed on the form (both years): sum line 45 per fund type into
lines 9–13; sum line 54 per fund type into lines 14, 17, 20, 23, 26; sum line
55 into lines 15, 18, 21, 24, 27; sum line 56 into lines 16, 19, 22, 25, 28 —
always "der ersten Anlage KAP-INV".

## Notes and ambiguities

### Anlage SO

- **Freigrenzen (sanity check, from the Anleitung).** §22 Nr. 3, 2024: "Haben
  Sie im Jahr 2024 Einkünfte aus Leistungen von insgesamt weniger als 256 €
  (Freigrenze) erzielt? Dann müssen Sie diese in der Anlage SO nicht eintragen.
  Bei einer Zusammenveranlagung gilt die Freigrenze i. H. v. 256 € für jede
  Person." The 2025 Anleitung has the same sentence with "2025". §23, 2024:
  "Haben Sie im Jahr 2024 Gewinne aus privaten Veräußerungsgeschäften von
  insgesamt weniger als 1.000 € (Freigrenze) erzielt? Dann müssen Sie diese in
  der Anlage SO nicht eintragen. Bei einer Zusammenveranlagung gilt die
  Freigrenze i. H. v. 1.000 € für jede Person." Same in 2025 with "2025". Both
  years therefore state 256 € and 1.000 €. The earlier 600 € figure was not
  checked against a 2023 Anleitung.
- **No Freigrenze line and no §23 grand total.** Neither year's form has a line
  for the Freigrenze or a line summing all §23 results. The closest things are
  the allocation line (54 / 58) and the further-disposals line (55 / 59). The
  Finanzamt applies the Freigrenze.
- **Losses are still to be declared.** Both years: "Wenn Sie innerhalb der oben
  genannten Fristen Verluste aus privaten Veräußerungsgeschäften realisiert
  haben, geben Sie diese bitte hier an." and for Leistungen: "Wenn Sie im Jahr
  2024 Verluste aus Leistungen erzielt haben, geben Sie diese bitte hier an."
- **"Loss carryback limitation" is a waiver checkbox.** There is no amount
  field limiting the carryback. Lines 18 / 62 (2024) and 22 / 66 (2025) are a
  yes-flag to forgo the carryback entirely. 2024 Anleitung: "Falls Sie auf die
  Verrechnung nach Maßgabe des § 10d Abs. 1 EStG (Verlustrücktrag ins Jahr
  2023) verzichten möchten, tragen Sie bitte in Zeile 18 eine „1“ ein." and
  "Die Erläuterungen zu Zeile 18 gelten auch für Einkünfte aus privaten
  Veräußerungsgeschäften."
- **Foreign currency belongs in "Andere Wirtschaftsgüter".** 2024 Anleitung:
  "In den Zeilen 48 bis 55 machen Sie Angaben zu Veräußerungen von anderen
  Wirtschaftsgütern, die keine Grundstücke oder grundstücksgleiche Rechte sowie
  virtuelle Währungen sind, wenn dabei der Zeitraum zwischen Anschaffung und
  Veräußerung nicht mehr als ein Jahr beträgt oder die Veräußerung vor dem
  Erwerb erfolgt (z. B. Fremdwährungen usw.)." 2025 Anleitung: "In den Zeilen
  52 bis 57 machen Sie Angaben zu Veräußerungen von anderen Wirtschaftsgütern,
  die keine Grundstücke oder grundstücksgleiche Rechte sowie Kryptowerte sind,
  … (z. B. Fremdwährungen usw.)."
- **Inconsistency inside the 2025 Anleitung.** The 2025 Anleitung text says "In
  den Zeilen 45 bis 49 sowie 56 und 57 machen Sie Angaben zu Veräußerungen von
  Kryptowerten". The 2025 form itself places crypto at lines 45–51 with
  allocation and further disposals at 58 and 59, and prints "Hinweis: Angaben
  zu privaten Veräußerungsgeschäften machen Sie bitte in den Zeilen 45 bis 51
  sowie 58 und 59." The table follows the form. The 2024 Anleitung ("Zeilen 41
  bis 47 sowie 54 und 55") matches the 2024 form.
- **One disposal per block.** Each §23 block has a single column for one
  disposal. For several disposals both Anleitungen say: "Bei mehreren
  Veräußerungen erläutern Sie diese bitte in einer gesonderten Aufstellung."
  The aggregate then goes on line 55 (2024) / 59 (2025).
- **BMF letter referenced.** 2024 Anleitung cites the BMF letter of 10 May 2022
  (BStBl I p. 668); the 2025 Anleitung cites the one of 6 March 2025 (BStBl I
  p. 658).

### Anlage KAP

- **JStG 2024 and the Termingeschäfte restriction.** The 2024 form was
  finalised in September 2024, before the law changed, and still carries the
  separate lines: 9, 14, 15 (withheld block) and 21, 24, 25 (non-withheld
  block). The 2024 Anleitung still describes the old limits: "Verluste aus
  Termingeschäften … verrechnet Ihr Finanzamt nur mit Gewinnen aus
  Termingeschäften und Einkünften aus Stillhalterprämien bis zu 20.000 €." and
  "Verluste aus Termingeschäften erklären Sie bitte ausschließlich in Zeile
  24." The 2025 form removes lines 21, 24 and 25 from the non-withheld block
  (printed "21 frei", "24 und 25 frei") but keeps lines 9, 14 and 15 in the
  withheld block. The 2025 Anleitung explains, under "Zeile 14 und 15", marked
  "Neu!": "Die Verlustverrechnungsbeschränkung nach § 20 Abs. 6 Satz 5 und 6
  EStG für Verluste aus … Termingeschäften wurde aufgehoben. Da nicht alle
  Banken umgehend ihre IT-Systeme umstellen konnten, kann es sein, dass Ihre
  Verluste in der Steuerbescheinigung noch als Verluste nach § 20 Abs. 6 Satz 5
  oder 6 EStG und mit Verweis auf die Zeilen 14 und / oder 15 ausgewiesen
  werden. Übernehmen Sie dann bitte die Daten aus der Steuerbescheinigung in
  die Anlage KAP. Ihr Finanzamt wird die erklärten Verluste automatisch mit
  allen positiven Kapitalerträgen für Sie verrechnen."
- **Where 2025 non-withheld Termingeschäfte and write-off losses go.** 2025
  Anleitung: "Liegt Ihnen keine (Steuer-)Bescheinigung Ihres ausländischen
  Kreditinstituts vor, entnehmen Sie die Verluste aus den Abrechnungsunterlagen
  des Kreditinstituts / der depotführenden Stelle. Tragen Sie die Ihnen
  entstandenen Verluste dann in die Zeilen 18 und / oder 19 und zusätzlich in
  Zeile 22 ein. Wenn es sich um Verluste aus der wertlosen Ausbuchung von
  Aktien handelt, tragen Sie die Verluste nicht in Zeile 22, sondern zusätzlich
  in Zeile 23 ein." The sentence order was reconstructed from a two-column
  extraction; the content is unambiguous but the exact sequence should be
  rechecked visually before quoting it elsewhere.
- **How the 2024 form should be filled for a year the repeal already covers**
  is not answered by the 2024 Anleitung (it predates the law). Not verified
  from a primary source.
- **Net-in-18/19, detail in 20–23.** Both years: "Alle
  Veräußerungstatbestände tragen Sie bitte zusätzlich in die Zeilen 20 und /
  oder 22 und / oder 23 ein. Das betrifft Gewinne und Verluste aus der
  Veräußerung von Kapitalanlagen (z. B. Aktien)." The "enthaltene" lines are
  sub-amounts of lines 18/19, not additions. 2024 adds: "Einkünfte aus
  Stillhalterprämien und Gewinne aus Termingeschäften tragen Sie bitte
  zusätzlich in Zeile 21 ein."
- **Domestic vs. foreign: decided by what the Anleitung says about the paying
  agent and the debtor.** Both years: "Tragen Sie bitte inländische
  Kapitalerträge, die bisher nicht dem Steuerabzug durch eine inländische
  Zahlstelle unterlegen haben (z. B. Zinsen aus Privatdarlehen unter fremden
  Dritten) in Zeile 18 ein." and "Zu den ausländischen Erträgen in Zeile 19
  gehören insbesondere Erträge bei ausländischen Kreditinstituten (z. B.
  Dividenden und Zinsen einer ausländischen Schuldnerin oder eines
  ausländischen Schuldners)."
  - Dividends of foreign companies held at a foreign broker: line 19. This is
    the Anleitung's own example.
  - Dividends of German companies held at a foreign broker: the Anleitung does
    not address this case. Its line-19 sentence names the foreign bank as the
    category and a foreign debtor as the example, so the two criteria point in
    different directions here. Not verified from a primary source. A further
    complication the Anleitung also leaves open: such dividends normally have
    German Kapitalertragsteuer deducted at source, which would make them income
    that did undergo domestic withholding, but without a German
    Steuerbescheinigung of the kind lines 7–15 expect.
- **Foreign withholding tax.** Both years: "Die bereits durch das Kreditinstitut
  angerechnete ausländische Steuer tragen Sie in Zeile 40, die noch nicht
  angerechnete ausländische Steuer in Zeile 41 (und nicht in der Anlage AUS)
  ein." For a foreign broker that credits nothing against German tax, that
  means line 41. Fictitious withholding tax: "Tragen Sie diese fiktive Steuer
  bitte in Zeile 42 ein und reichen entsprechende Nachweise in Kopie ein."
  The Anleitung also says of the non-withheld block: "Die Einkommensteuer auf
  diese Kapitalerträge beträgt 25 %. Ihr Finanzamt berücksichtigt dabei
  anrechenbare ausländische Steuer …".
- **Gross or net of foreign tax on line 19** is not stated explicitly in the
  Anlage KAP Anleitung for either year. (Anlage KAP-INV does state it for fund
  distributions, see below.) Not verified from a primary source.
- **No "tax due" line.** Confirmed for both years: the form runs from line 1 to
  line 55 and contains income, loss, Sparer-Pauschbetrag, request and
  tax-credit lines only. The only tax amounts entered are taxes already
  withheld or creditable (lines 37–45, 53). The Finanzamt computes the tax; the
  Anleitung: "Die Einkommensteuer auf diese Kapitalerträge beträgt 25 %."
- **Sparer-Pauschbetrag.** Both years state 1.000 € / 2.000 € and: "In die
  Zeilen 16 und 17 müssen Sie die Höhe des Sparer-Pauschbetrags eintragen, den
  Sie aufgrund von Freistellungsaufträgen bereits in Anspruch genommen haben
  (ggf. „0“)." With only non-withheld income, line 17 is still required: "In
  diesem Fall müssen Sie auch Angaben zum Sparer-Pauschbetrag in Zeile 17
  machen." Exception: "Wenn Sie die Günstigerprüfung (Zeile 4) beantragen,
  dürfen Sie keine Eintragung in Zeile 17 vornehmen."
- **Duty to declare below the Sparer-Pauschbetrag (2025 wording).** The 2025
  Anleitung adds to the non-withheld case: "(eine Erklärungspflicht besteht
  auch, wenn die Kapitalerträge den Sparer-Pauschbetrag nicht übersteigen)".
  The 2024 Anleitung does not contain this parenthesis.
- **Other 2024 → 2025 label changes seen on the form:** line 29 dropped the
  clause "Verluste aus der ganzen oder teilweisen Uneinbringlichkeit der
  Kapitalforderungen"; line 54 refers to "Zeile 28 der Anlage AUS" instead of
  "Zeile 26"; lines 35 and 36 refer to different Anlage KAP-BET lines.

### Anlage KAP-INV

- **Amounts are entered before Teilfreistellung.** Identical in both years:
  "Bitte beachten Sie, dass Sie sämtliche Investmenterträge in voller Höhe (vor
  Teilfreistellung und einschließlich des ausländischen Steuerabzugs) angeben
  müssen. Die Teilfreistellung wird vom Finanzamt berücksichtigt." Also:
  "Veräußerungsgewinne und -verluste geben Sie bitte in den Zeilen 14 bis 28
  an. Tragen Sie diese zur zutreffenden Anwendung der Teilfreistellung jeweils
  getrennt nach Fondsart ein." The form repeats "(vor Teilfreistellung)" on
  every fund-type line except "sonstige Investmentfonds", which have no
  Teilfreistellung.
- **Line 53 is also before Teilfreistellung.** "… tragen Sie hier bitte die
  während der Besitzzeit der veräußerten Investmentanteile angesetzten
  Vorabpauschalen ein. Sie müssen diese vor Teilfreistellung angeben."
- **Scope: only fund income without German withholding.** Both years: "Die
  Anlage KAP-INV ist für Ihre Angaben zu Investmenterträgen vorgesehen, die
  nicht dem inländischen Steuerabzug unterlegen haben." and "Dies ist z. B. der
  Fall, wenn Ihre Investmentanteile im Ausland verwahrt werden." The Anlage KAP
  Anleitung mirrors it: "Ausschüttungen aus Investmentfonds sowie
  Veräußerungen von Investmentanteilen, die nicht dem inländischen Steuerabzug
  unterlegen haben, tragen Sie bitte in die Anlage KAP-INV ein." Fund income
  that was subject to German withholding is therefore not entered on Anlage
  KAP-INV; it reaches Anlage KAP through the Steuerbescheinigung amounts in
  lines 7–15 (line 10 exists specifically for grandfathered fund units sold
  with withholding). That last step is the reading that follows from both
  Anleitungen; neither states in one sentence "withheld fund income goes on
  Anlage KAP".
- **Whether the Steuerbescheinigung amounts in Anlage KAP line 7 are already
  after Teilfreistellung** is not stated in the Anleitungen read. Not verified
  from a primary source.
- **Foreign tax on fund income.** Both years, reconstructed across a column
  break: "Die anrechenbare ausländische Steuer auf Investmenterträge, die nicht
  dem inländischen Steuerabzug unterlegen haben, tragen Sie bitte in Zeile 41
  der Anlage KAP (und nicht in der Anlage AUS) ein." Distributions are entered
  gross: the heading reads "einschließlich des ausländischen Steuerabzugs auf
  den Kapitalertrag".
- **Sparer-Pauschbetrag link.** "Bitte machen Sie in diesen Fällen auch die
  Angaben zum Sparer-Pauschbetrag in Zeile 17 der Anlage KAP, außer wenn Sie
  die Günstigerprüfung beantragen." (reconstructed across a column break).
- **Year offset in the Vorabpauschale block.** The 2024 form computes the
  Vorabpauschale from 2023 prices (rate 1,785 %), the 2025 form from 2024
  prices (rate 1,603 %), because the Vorabpauschale for a calendar year counts
  as received at the start of the following year.

### Not verified from a primary source

- Which Anlage KAP line takes dividends of German companies held at a foreign
  broker (both years).
- Whether Anlage KAP line 19 is entered gross or net of foreign withholding tax
  (both years).
- How to fill the 2024 Anlage KAP lines 21, 24 and 25 given that the repeal of
  the Termingeschäfte restriction came after the 2024 form and Anleitung were
  finalised.
- Whether Steuerbescheinigung figures entered in Anlage KAP line 7 for fund
  income are after Teilfreistellung.
- The pre-2024 §23 Freigrenze of 600 € (no 2023 Anleitung was read).
- Exact sentence order of three quotes reconstructed from multi-column PDF text
  (marked above); wording is from the source, layout was not checked visually.
- The rendered print PDFs of the forms were not opened; the FMS HTML forms
  were. A layout difference between the two is not expected but was not ruled
  out.
