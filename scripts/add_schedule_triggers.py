#!/usr/bin/env python3
"""Ajoute un Schedule Trigger (cron + timezone ET) en parallèle du Webhook
sur les workflows T8 mailer, T17 sync, T18 weekly.

Le Schedule fire automatiquement aux heures voulues + le webhook reste
disponible pour tests manuels.
"""

import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

N8N = os.environ["N8N_BASE_URL"]
K   = os.environ["N8N_API_KEY"]
H = {"X-N8N-API-KEY": K, "Content-Type": "application/json"}

# Mapping : workflow name → cron expression (NY timezone) + description
SCHEDULES = {
    "DailySmileCare-v2-Approval-Mailer": {
        "cron": "0 9 * * *",       # 09h00 chaque jour
        "desc": "Mailer 09h00 ET",
    },
    "DailySmileCare-v2-Affiliate-Sync": {
        "cron": "0 23 * * *",      # 23h00 chaque jour
        "desc": "Affiliate sync 23h00 ET",
    },
    "DailySmileCare-v2-Weekly-Report": {
        "cron": "0 8 * * 1",        # Lundi 08h00
        "desc": "Weekly report lundi 08h00 ET",
    },
}


def get_workflow(wf_id):
    r = requests.get(f"{N8N}/api/v1/workflows/{wf_id}", headers=H)
    if r.status_code >= 400: raise RuntimeError(f"GET wf {wf_id}: {r.text[:300]}")
    return r.json()


def update_workflow(wf_id, wf_payload):
    """PUT updated workflow."""
    # Clean fields that aren't allowed in PUT
    allowed = {"name", "nodes", "connections", "settings", "staticData"}
    payload = {k: v for k, v in wf_payload.items() if k in allowed}
    r = requests.put(f"{N8N}/api/v1/workflows/{wf_id}", headers=H, json=payload)
    if r.status_code >= 400: raise RuntimeError(f"PUT wf {wf_id}: {r.text[:600]}")
    return r.json()


def add_schedule_to_workflow(wf, cron_expr):
    """Add a Schedule Trigger node connected to whatever the Webhook trigger
    is connected to. Returns modified workflow."""
    nodes = wf["nodes"]
    connections = wf["connections"]

    # Find the existing Webhook trigger node
    webhook_node = next((n for n in nodes if n.get("type") == "n8n-nodes-base.webhook"
                         and (n.get("parameters", {}).get("httpMethod") == "POST"
                              or "Trigger" in n.get("name", "")
                              or "Webhook" in n.get("name", ""))), None)
    if not webhook_node:
        raise RuntimeError("No Webhook trigger found in workflow")

    wh_name = webhook_node["name"]
    # Find what the webhook is connected to
    webhook_outputs = connections.get(wh_name, {}).get("main", [[]])
    if not webhook_outputs or not webhook_outputs[0]:
        raise RuntimeError(f"Webhook '{wh_name}' has no downstream connection")
    downstream_node_name = webhook_outputs[0][0]["node"]

    # Remove any existing Schedule trigger (idempotent re-runs)
    nodes = [n for n in nodes if n.get("type") != "n8n-nodes-base.scheduleTrigger"]
    if "Schedule" in connections:
        del connections["Schedule"]

    # Add Schedule trigger
    schedule_node = {
        "id": "sched",
        "name": "Schedule",
        "type": "n8n-nodes-base.scheduleTrigger",
        "typeVersion": 1.2,
        "position": [webhook_node["position"][0], webhook_node["position"][1] + 200],
        "parameters": {
            "rule": {
                "interval": [
                    {
                        "field": "cronExpression",
                        "expression": cron_expr,
                    },
                ],
            },
        },
    }
    nodes.append(schedule_node)
    connections["Schedule"] = {"main": [[{"node": downstream_node_name, "type": "main", "index": 0}]]}

    wf["nodes"] = nodes
    wf["connections"] = connections
    # Workflow timezone — n8n cron uses this
    settings = wf.get("settings", {})
    settings["timezone"] = "America/New_York"
    wf["settings"] = settings

    return wf


def main():
    print("=== Add Schedule Triggers ===\n")
    # Fetch all workflows
    r = requests.get(f"{N8N}/api/v1/workflows", headers=H)
    all_wfs = {w["name"]: w["id"] for w in r.json().get("data", [])}

    for name, cfg in SCHEDULES.items():
        wf_id = all_wfs.get(name)
        if not wf_id:
            print(f"  ✗ {name}: NOT FOUND in n8n"); continue
        print(f"  → {name} (id={wf_id})")
        wf = get_workflow(wf_id)
        try:
            new_wf = add_schedule_to_workflow(wf, cfg["cron"])
            update_workflow(wf_id, new_wf)
            # Re-activate (PUT may deactivate)
            requests.post(f"{N8N}/api/v1/workflows/{wf_id}/activate", headers=H)
            print(f"    ✓ Schedule '{cfg['cron']}' ET ajouté ({cfg['desc']})")
        except Exception as e:
            print(f"    ✗ Failed: {e}")

    print("\n✓ Schedule triggers configurés. Les workflows tournent maintenant en automatique.")
    print("  - Mailer : tous les jours à 09h00 ET")
    print("  - Affiliate sync : tous les jours à 23h00 ET")
    print("  - Weekly report : tous les lundis à 08h00 ET")
    print()
    print("Les webhooks restent disponibles pour tests manuels si besoin.")


if __name__ == "__main__":
    main()
