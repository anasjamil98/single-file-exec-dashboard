# single-file-exec-dashboard

An interactive dashboard for leadership that's one HTML file. No login, no server, no install. It opens from an email attachment and works on a plane.

**[Open the dashboard](dist/dashboard.html)** (download it and double-click, or see it running on the portfolio site).

## The problem

A senior reader asks for a regular file: payment value by type, the biggest merchants, how it's moving. The usual answer is a spreadsheet every 2 weeks. They can't filter it, so every follow-up question comes back to you as another request.

The usual upgrade is a BI tool. That means a licence, a login, a VPN, and a link that doesn't open on a phone 5 minutes before a board meeting.

There's a third option that gets overlooked. Do the aggregation once, put the result inside 1 HTML file with the charts and filters, and send that. Your reader explores it themselves. Nothing has to be provisioned. And because the file holds aggregates only, nothing sensitive travels with it.

## What's in the file

It's 88 KB, data included. For 2025 it opens on MRD 6.99M of payment value across 146.5K payments, at a 93.4% success rate.

- **Filters** in 1 row: 5 period presets, a custom month range, and payment type. Everything below re-scopes together, so the tiles and charts always agree. Pick Q4 and payment value reads MRD 2.22M, up 17.2% on Q3.
- **5 headline figures**, each with the change against the previous period of the same length.
- **Payment value by month**, 12 columns stacked by the 4 payment types. Months outside your selection fade but stay visible, so a quarter is always read against the year.
- **Payment value by type**, ranked, with share. Transfers to people lead at 46%.
- **Top 10 merchants** of 130, with category, payments, value and share.
- A **table view** behind every chart, and tooltips that work from the keyboard as well as the mouse.
- Light and dark mode, following your system setting.

## How it's built

```
zaffre.db
    |
    v
build_dashboard.py      aggregates to month x type (x merchant), folds small cells
    |
    v
template.html           plain HTML, CSS and JavaScript; inline SVG; no libraries
    |
    v
dist/dashboard.html     one file, data embedded as JSON
```

I wrote the charts by hand in about 430 lines of plain JavaScript. There isn't a single dependency in the browser.

## Run it

You need Python 3.9 or later.

```bash
pip install -r requirements.txt
```

```bash
python data/generate.py
```

```bash
python build_dashboard.py
```

```bash
python -m pytest
```

The build prints what it kept and what it folded:

```
Wrote dist/dashboard.html (88 KB)
48 month x type cells, 2821 merchant cells shown, 17 small-cell groups folded (274 payments)
```

## What leaves the database is decided in Python, not in the browser

Anything you embed in an HTML file can be read by whoever has the file. Hiding a column in the interface protects nothing. So I run the privacy rules at build time, before the data is written.

**Aggregates only.** The finest grain in the file is month by payment type by merchant: 48 cells for the charts and 2,821 for the merchant table. There's no customer id and no individual transaction, and a test checks the payload for both.

**Small cells are folded.** A merchant's month is only listed when at least 5 different customers paid there. Below that, I fold the row into a single "not shown" line. On the full dataset that's 17 groups covering 274 payments. Totals still add up, and a test proves it: shown cells plus folded cells equals every merchant payment in the source.

**No external requests.** The build fails if the output references any URL. No CDN, no web fonts, no analytics. That makes it safe to open inside a network that blocks outbound traffic, and it's why the thing works offline.

**Embedded data can't break out.** A merchant called `</script>` would otherwise end the data block early. I escape it at build time and write every label to the page as text, never as HTML. 1 of the 14 tests tries exactly that attack.

## Chart decisions

**1 axis, always.** Value and count never share a plot.

**Colour follows the payment type, not its rank.** Card payments are the same green in every chart and under every filter. Pick a single type and you see that type alone in its own colour. The legend disappears, because the subtitle already names it.

**The merchant bars are grey on purpose.** They're 1 series, so they get 1 colour, and it isn't any of the 4 type colours. Blue there would read as "transfers to people".

**Fading, not removing.** Choose Q4 and January to September fade but stay on the chart. A quarter shown alone has no context, and 3 columns isn't much of a chart.

**Distinct customers aren't added up.** Someone who made a card payment and a bill payment in March is 1 paying customer, not 2. So I count "paying customers" across all types separately at build time. For 2025 the monthly average is 2,375.

**Nothing is readable only by hovering.** Every figure in a tooltip is also in the table view.

The 4 type colours come from a categorical palette designed for colour-blind separation, used in its documented order, with separate steps for dark mode. 2 of the 4 sit below 3:1 contrast on a light background. That's why the legend, the direct labels and the table view are all there.

## The messy part

- **The data is frozen at build time.** That's the trade. For a leadership file every 2 weeks it's the right one. For anything operational it isn't.
- **Size has a ceiling.** Monthly grain for a year is 88 KB. Daily grain by merchant would be a few megabytes. Somewhere past that, 1 file stops being the right answer.
- **The threshold of 5 is a judgment call.** It's a common choice for small-cell suppression. The right number depends on your data and on who's receiving the file, and that's a conversation to have with whoever owns data protection.
- **Suppression is per month.** A merchant with 4 customers in each of 3 months is hidden in each, though it may have 12 different customers across the quarter. That errs towards hiding too much, which is the safe direction.
- **Hand-written charts cut both ways.** The file stays small and dependency-free. But when someone asks me for a new chart type, there's no library to lean on.

## About the data

Every row is generated by [`data/generate.py`](data/generate.py) from a fixed seed: 4,000 customers and 194,707 transactions across 2025. Zaffre Wallet, its merchants and its currency are invented. No design, figure or code here comes from an employer's systems.

## Licence

MIT
