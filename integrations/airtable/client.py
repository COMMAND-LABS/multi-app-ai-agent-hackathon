"""Minimal Airtable REST client (personal access token from .env).

Scopes the token needs: data.records:read, data.records:write, schema.bases:read,
and schema.bases:write if you want `ensure_table` to create the table for you.
"""

from __future__ import annotations

from typing import Any

import requests

from integrations.config import settings

API = "https://api.airtable.com/v0"
BATCH = 10  # Airtable's max records per write request


class AirtableAPIError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"Airtable API {status}: {message}")
        self.status = status


class AirtableClient:
    def __init__(self, api_key: str | None = None, base_id: str | None = None, timeout: int = 30):
        self.api_key = api_key if api_key is not None else settings.airtable.api_key
        self.base_id = base_id if base_id is not None else settings.airtable.base_id
        self.timeout = timeout
        if not self.api_key:
            raise AirtableAPIError(0, "AIRTABLE_API_KEY is not set in .env")
        if not self.base_id:
            raise AirtableAPIError(0, "AIRTABLE_BASE_ID is not set in .env (looks like appXXXXXXXXXXXXXX)")
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {self.api_key}"

    def _req(self, method: str, path: str, **kw) -> dict:
        resp = self.session.request(method, f"{API}{path}", timeout=self.timeout, **kw)
        if resp.status_code >= 400:
            try:
                err = resp.json().get("error", {})
                msg = err.get("message", resp.text) if isinstance(err, dict) else str(err)
            except ValueError:
                msg = resp.text
            raise AirtableAPIError(resp.status_code, msg)
        return resp.json() if resp.content else {}

    # ---------------------------------------------------------------- schema
    def list_tables(self) -> list[dict]:
        return self._req("GET", f"/meta/bases/{self.base_id}/tables").get("tables", [])

    def find_table(self, name: str) -> dict | None:
        return next((t for t in self.list_tables() if t["name"] == name or t["id"] == name), None)

    def create_table(self, name: str, fields: list[dict], description: str = "") -> dict:
        body: dict[str, Any] = {"name": name, "fields": fields}
        if description:
            body["description"] = description
        return self._req("POST", f"/meta/bases/{self.base_id}/tables", json=body)

    def ensure_table(self, name: str, fields: list[dict], description: str = "") -> tuple[dict, bool]:
        """Return (table, created)."""
        existing = self.find_table(name)
        if existing:
            return existing, False
        return self.create_table(name, fields, description), True

    # --------------------------------------------------------------- records
    def list_records(self, table: str, filter_formula: str | None = None, fields: list[str] | None = None) -> list[dict]:
        out, offset = [], None
        while True:
            params: dict[str, Any] = {"pageSize": 100}
            if filter_formula:
                params["filterByFormula"] = filter_formula
            if fields:
                params["fields[]"] = fields
            if offset:
                params["offset"] = offset
            data = self._req("GET", f"/{self.base_id}/{table}", params=params)
            out.extend(data.get("records", []))
            offset = data.get("offset")
            if not offset:
                return out

    def upsert(self, table: str, records: list[dict], merge_on: list[str]) -> dict:
        """Create-or-update records (list of field dicts) matched on `merge_on` fields.
        Returns {"created": [...ids], "updated": [...ids], "records": [...]}."""
        result = {"created": [], "updated": [], "records": []}
        for i in range(0, len(records), BATCH):
            batch = records[i : i + BATCH]
            data = self._req(
                "PATCH",
                f"/{self.base_id}/{table}",
                json={"performUpsert": {"fieldsToMergeOn": merge_on}, "records": [{"fields": r} for r in batch], "typecast": True},
            )
            result["created"] += data.get("createdRecords", [])
            result["updated"] += data.get("updatedRecords", [])
            result["records"] += data.get("records", [])
        return result

    def create(self, table: str, records: list[dict]) -> list[dict]:
        out = []
        for i in range(0, len(records), BATCH):
            data = self._req("POST", f"/{self.base_id}/{table}", json={"records": [{"fields": r} for r in records[i : i + BATCH]], "typecast": True})
            out += data.get("records", [])
        return out
