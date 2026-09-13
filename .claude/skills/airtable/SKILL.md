---
name: airtable
description: Read or write Airtable via the project's REST client (.env token) — push pipeline results, list tables/records, create tables. Use for any Airtable request; prefer the CLI push for pipeline output so it is logged and produces a sync report.
---

# Airtable integration

Credentials in `.env`: `AIRTABLE_API_KEY` (personal access token) and `AIRTABLE_BASE_ID` (`app...`).
Token scopes needed: `data.records:read`, `data.records:write`, `schema.bases:read`, and
`schema.bases:write` for automatic table creation. If they are missing, tell the user which
variable to fill; never ask for the token in chat.

## Push pipeline results

```bash
uv run python -m integrations.airtable.push [--run-id X] [--table "Repeatable Ideas"] [--all] [--dry-run]
```

Reads `reports/<run_id>/repeatability.csv`, pushes repeatable ideas (or all with `--all`), creates
the table on first use with the schema in `integrations/airtable/push.py`, and writes
`reports/<run_id>/airtable_sync.md` with the record IDs. Upserts on **Run ID + Source Video ID**.

Table columns: Idea, Run ID, Found At, Status (New / In progress / Used / Rejected), Repeatable,
Source Channel, Source Video ID, Source URL, Source Views, Outlier Multiple, Topic Query,
Repeatability Score, Similar Videos, Strong Hits, Median Match Views, Evidence, Description, Report.
Downstream content generation should pick rows with Status = New.

## Ad-hoc use

```python
from integrations.airtable import AirtableClient
c = AirtableClient()
c.list_tables()
c.list_records("Repeatable Ideas", filter_formula="{Status}='New'")
c.upsert("Repeatable Ideas", [{"Idea": "...", "Run ID": "...", "Source Video ID": "..."}], ["Run ID", "Source Video ID"])
```

An Airtable MCP connector may also be available in the session; it is fine for reading or
inspecting, but keep pipeline writes on the CLI so they appear in the tool-call log and sync report.
