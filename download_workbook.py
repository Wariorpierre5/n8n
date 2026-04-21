#!/usr/bin/env python3
"""
Download every tab of the 'Niche Brosse à dents' Google Sheet as individual CSV files.

Prerequisites:
  pip install google-auth google-auth-oauthlib google-api-python-client

Setup (once):
  1. Go to https://console.cloud.google.com/apis/credentials
  2. Create an OAuth 2.0 Client ID (Desktop app)
  3. Download the JSON and save it as 'credentials.json' next to this script
"""

import csv
import os
import pickle
from pathlib import Path

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
WORKBOOK_NAME = "Niche Brosse à dents"
OUTPUT_DIR = Path("csv_exports")
TOKEN_FILE = "token.pickle"
CREDENTIALS_FILE = "credentials.json"


def get_credentials():
    creds = None
    if Path(TOKEN_FILE).exists():
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not Path(CREDENTIALS_FILE).exists():
                raise FileNotFoundError(
                    f"Fichier '{CREDENTIALS_FILE}' introuvable.\n"
                    "Télécharge-le depuis https://console.cloud.google.com/apis/credentials "
                    "(OAuth 2.0 Client ID → Desktop app)."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
    return creds


def find_spreadsheet(drive_service, name):
    query = (
        f"name = '{name}' "
        "and mimeType = 'application/vnd.google-apps.spreadsheet' "
        "and trashed = false"
    )
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    if not files:
        raise ValueError(f"Aucun classeur nommé '{name}' trouvé dans ton Drive.")
    if len(files) > 1:
        print(f"Plusieurs classeurs trouvés — utilisation du premier : {files[0]['id']}")
    return files[0]["id"]


def slugify(name):
    """Turn a sheet title into a safe filename."""
    return "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()


def export_all_tabs(sheets_service, spreadsheet_id, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)

    spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheets = spreadsheet.get("sheets", [])

    print(f"{len(sheets)} onglet(s) trouvé(s) dans '{WORKBOOK_NAME}':\n")

    for sheet in sheets:
        title = sheet["properties"]["title"]
        filename = output_dir / f"{slugify(title)}.csv"

        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=title,
        ).execute()
        rows = result.get("values", [])

        # Pad rows to uniform width so the CSV is well-formed
        max_cols = max((len(r) for r in rows), default=0)
        padded = [r + [""] * (max_cols - len(r)) for r in rows]

        with open(filename, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(padded)

        print(f"  ✓ '{title}' → {filename}  ({len(rows)} lignes)")

    print(f"\nExport terminé dans le dossier '{output_dir.resolve()}'")


def main():
    creds = get_credentials()
    drive_service = build("drive", "v3", credentials=creds)
    sheets_service = build("sheets", "v4", credentials=creds)

    spreadsheet_id = find_spreadsheet(drive_service, WORKBOOK_NAME)
    export_all_tabs(sheets_service, spreadsheet_id, OUTPUT_DIR)


if __name__ == "__main__":
    main()
