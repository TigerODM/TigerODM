# Serveur MCP (Model Context Protocol) devant l'API REST HLIT (server_uvicorn.py).
#
# Permet à un LLM local (front TigerHost / webui llama.cpp, LM Studio...) de
# lister et lancer les workflows HLIT. Ce serveur ne contient aucune logique
# métier : il traduit les appels d'outils MCP en appels HTTP vers l'API HLIT,
# qui doit tourner (par défaut http://127.0.0.1:8000).
#
# Cycle d'exécution d'un workflow côté API HLIT :
#   1. GET  /start-workflow/{key_name}  -> lance Orange sur le .ows
#      (404 "workflow is already running" si déjà ouvert : ce n'est pas une erreur)
#   2. POST /input-workflow             -> dépose les tables d'entrée ;
#      202 "The workflow is starting" tant qu'Orange charge (on réessaie)
#   3. GET  /output-workflow/{workflow_id} -> 202 tant que ça tourne, 200 à la fin
# Le workflow_id n'est PAS le key_name : c'est une propriété des widgets
# « Input Interface » du .ows (lue via /get-worklow-id-list/{key_name}).
#
# Le front TigerHost appelle les outils avec le timeout par défaut du SDK MCP
# (60 s, non prolongé par les notifications de progression) : aucun outil ne
# bloque plus de WAIT_MAX_S. Un workflow plus long renvoie "running" et le
# modèle récupère le résultat avec get_workflow_result.
#
# Dépendance : pip install "mcp==2.3.0"   (httpx, starlette et uvicorn sont déjà là)
#
# Lancement (HTTP, pour le front TigerHost) :
#   python mcp_server.py --port 8001
#   puis dans le front : ajouter le serveur MCP http://127.0.0.1:8001/mcp
# Lancement (stdio, pour LM Studio, Claude Desktop...) :
#   python mcp_server.py --stdio

import argparse
import json
import logging
import math
import os
import time

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

HLIT_API_URL = os.getenv("HLIT_API_URL", "http://127.0.0.1:8000").rstrip("/")
HLIT_API_KEY = os.getenv("HLIT_API_KEY", "")
API_KEY_NAME = "HLIT-API-Key"

# attente max par appel d'outil (< 60 s du client)
WAIT_MAX_S = float(os.getenv("HLIT_MCP_WAIT_S", "45"))
POLL_S = 1.0             # intervalle de scrutation de l'API
MAX_ROWS = 50            # lignes de résultat renvoyées au modèle
MAX_CHARS = 20000        # taille max du résultat sérialisé
EXAMPLE_CHARS = 200      # troncature des exemples dans describe_workflow

INSTRUCTIONS = (
    "Outils pour piloter les workflows HLIT (Orange). Démarche : list_workflows pour "
    "trouver le key_name, describe_workflow pour connaître les colonnes d'entrée, puis "
    "run_workflow. Si run_workflow renvoie status 'starting', rappelez-le avec les mêmes "
    "arguments ; s'il renvoie 'running', appelez get_workflow_result avec le workflow_id."
)

mcp = MCPServer("hlit", instructions=INSTRUCTIONS)


# ── Accès à l'API REST HLIT ─────────────────────────────────────────────────

class HlitApiError(ToolError):
    """Erreur prévue : renvoyée au modèle (isError) avec ce message."""


def _client():
    headers = {API_KEY_NAME: HLIT_API_KEY} if HLIT_API_KEY else {}
    return httpx.Client(base_url=HLIT_API_URL, headers=headers, timeout=30)


def _request(method, path, **kwargs):
    """Appel HTTP -> (status_code, json|texte). Erreur explicite si l'API est arrêtée."""
    try:
        with _client() as c:
            r = c.request(method, path, **kwargs)
    except httpx.ConnectError:
        raise HlitApiError(
            f"L'API HLIT ne répond pas sur {HLIT_API_URL}. Lancez server_uvicorn.py "
            f"(ou un workflow qui la démarre) puis réessayez.")
    except httpx.HTTPError as e:
        raise HlitApiError(f"Erreur de communication avec l'API HLIT : {e}")
    if r.status_code == 403:
        raise HlitApiError("Clé API refusée par l'API HLIT (variable HLIT_API_KEY).")
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text


def _message(body):
    if isinstance(body, dict):
        return str(body.get("_message") or body.get("message") or body.get("error") or "")
    return str(body)


def _workflows():
    code, body = _request("GET", "/read-config-file-ows-html")
    if code != 200 or not isinstance(body, dict):
        raise HlitApiError(f"Lecture de la liste des workflows impossible : {_message(body)}")
    return body.get("message") or []


def _interfaces(key_name):
    """Nœuds Input/Output Interface du workflow (cf. extract_property_for_hlit)."""
    code, body = _request("GET", f"/get-worklow-id-list/{key_name}")
    if code != 200 or not isinstance(body, list):
        raise HlitApiError(
            f"Workflow '{key_name}' introuvable ou illisible : {_message(body)}. "
            f"Utilisez list_workflows pour voir les key_name disponibles.")
    return body


def _input_spec(node):
    """(colonnes, types, ligne_exemple) d'une Input Interface d'après expected_input."""
    try:
        values = node["expected_input"]["data"][0]["values"]
        cols, types = list(values[0]), list(values[1])
        example = values[2][0] if values[2] else []
    except (KeyError, IndexError, TypeError):
        return [], [], []
    return cols, types, example


def _short(v):
    if isinstance(v, str) and len(v) > EXAMPLE_CHARS:
        return v[:EXAMPLE_CHARS] + "…"
    return v


# ── Construction des tables d'entrée ────────────────────────────────────────

def _to_float(v):
    if v is None or v == "":
        return math.nan
    if isinstance(v, bool):
        return float(v)
    return float(str(v).replace(",", ".")) if isinstance(v, str) else float(v)


def _build_table(rows, cols, types):
    """Lignes [{colonne: valeur}] -> format HLIT [[colonnes], [types], [[valeurs]]].

    Colonnes et types viennent de l'Input Interface ; une colonne inconnue du
    workflow est ajoutée (type déduit de la première valeur)."""
    cols, types = list(cols), list(types)
    for r in rows:
        for k, v in r.items():
            if k not in cols:
                cols.append(k)
                types.append("float" if isinstance(v, (int, float)) and not isinstance(v, bool)
                             else "str")
    data = []
    for i, r in enumerate(rows):
        line = []
        for c, t in zip(cols, types):
            v = r.get(c)
            if t == "float":
                try:
                    line.append(_to_float(v))
                except (TypeError, ValueError):
                    raise HlitApiError(
                        f"Ligne {i}, colonne '{c}' : '{v}' n'est pas un nombre.")
            else:
                line.append("" if v is None else str(v))
        data.append(line)
    return [cols, types, data]


# ── Mise en forme des résultats ─────────────────────────────────────────────

def _compact_result(data):
    """Limite la taille du résultat renvoyé au modèle."""
    note = None
    if isinstance(data, list) and len(data) > MAX_ROWS:
        note = f"{len(data)} lignes, seules les {MAX_ROWS} premières sont renvoyées."
        data = data[:MAX_ROWS]
    text = json.dumps(data, ensure_ascii=False, default=str)
    if len(text) > MAX_CHARS:
        note = (note + " " if note else "") + f"Résultat tronqué à {MAX_CHARS} caractères."
        data = text[:MAX_CHARS] + "…"
    return data, note


def _poll_output(workflow_id, deadline):
    """Scrute /output-workflow jusqu'à la fin du workflow ou la deadline."""
    last = None
    while True:
        code, body = _request("GET", f"/output-workflow/{workflow_id}")
        statut = body.get("_statut") if isinstance(body, dict) else None
        if code == 200:
            result, note = _compact_result(body.get("_result"))
            out = {"status": "finished", "workflow_id": workflow_id, "result": result}
            if statut == "You have file to get":
                out["files"] = (f"Le workflow a produit des fichiers : "
                                f"{HLIT_API_URL}/get-file-output-workflow/{workflow_id}")
            if note:
                out["note"] = note
            return out
        if statut == "Timeout":
            return {"status": "timeout", "workflow_id": workflow_id,
                    "message": "Le timeout du workflow est atteint, aucune sortie."}
        if code == 404:
            return {"status": "not_found", "workflow_id": workflow_id,
                    "message": "Aucune exécution en cours pour ce workflow_id "
                               "(résultat déjà récupéré, ou exécution jamais lancée)."}
        last = statut
        if time.time() >= deadline:
            out = {"status": "running", "workflow_id": workflow_id,
                   "message": "Le workflow tourne encore : appelez get_workflow_result "
                              "avec ce workflow_id."}
            if last:
                out["progress"] = last
            return out
        time.sleep(POLL_S)


# ── Outils MCP ──────────────────────────────────────────────────────────────

@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
def list_workflows() -> dict:
    """Liste les workflows HLIT disponibles (key_name et description)."""
    wfs = _workflows()
    return {"workflows": [
        {"key_name": w.get("name"), "description": w.get("description", "")}
        for w in wfs if "_temp_" not in str(w.get("name", ""))
    ]}


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
def describe_workflow(key_name: str) -> dict:
    """Décrit les entrées attendues (colonnes, types, exemple) et les sorties d'un workflow.

    Args:
        key_name: nom du workflow, tel que renvoyé par list_workflows.
    """
    nodes = _interfaces(key_name)
    inputs, outputs = [], []
    for n in nodes:
        if n.get("node_name") == "Input Interface":
            cols, types, example = _input_spec(n)
            inputs.append({
                "workflow_id": n.get("workflow_id"),
                "input_id": str(n.get("input_id")),
                "description": n.get("help_description") or "",
                "columns": [{"name": c, "type": t} for c, t in zip(cols, types)],
                "example_row": {c: _short(v) for c, v in zip(cols, example)},
            })
        elif n.get("node_name") == "Output Interface":
            sample = n.get("expected_output")
            first = sample[0] if isinstance(sample, list) and sample else {}
            outputs.append({
                "workflow_id": n.get("workflow_id"),
                "description": n.get("help_description") or "",
                "columns": list(first) if isinstance(first, dict) else [],
                "example_row": ({k: _short(v) for k, v in first.items()}
                                if isinstance(first, dict) else None),
            })
    return {"key_name": key_name, "inputs": inputs, "outputs": outputs}


@mcp.tool()
def run_workflow(key_name: str, rows: list[dict], input_id: str = "",
                 other_inputs: dict[str, list[dict]] | None = None,
                 timeout_s: int = 3600) -> dict:
    """Lance un workflow HLIT avec des données d'entrée et renvoie sa sortie.

    Attend au plus ~45 s. Si status = 'starting' (Orange se charge), rappelez
    run_workflow avec les mêmes arguments. Si status = 'running', appelez
    get_workflow_result avec le workflow_id renvoyé.

    Args:
        key_name: nom du workflow (list_workflows).
        rows: lignes d'entrée, une liste d'objets {colonne: valeur} ; colonnes
            données par describe_workflow.
        input_id: entrée visée par rows (vide = la première entrée du workflow).
        other_inputs: pour un workflow à plusieurs entrées, {input_id: lignes}.
        timeout_s: durée max d'exécution côté workflow, en secondes.
    """
    deadline = time.time() + WAIT_MAX_S
    nodes = [n for n in _interfaces(key_name) if n.get("node_name") == "Input Interface"]
    if not nodes:
        raise HlitApiError(f"Le workflow '{key_name}' n'a pas de widget Input Interface.")
    by_id = {str(n.get("input_id")): n for n in nodes}
    target = input_id or str(nodes[0].get("input_id"))
    if target not in by_id:
        raise HlitApiError(f"input_id '{target}' inconnu ; entrées disponibles : {sorted(by_id)}.")
    workflow_id = by_id[target].get("workflow_id")

    given = {target: rows}
    for k, v in (other_inputs or {}).items():
        if str(k) not in by_id:
            raise HlitApiError(f"input_id '{k}' inconnu ; entrées disponibles : {sorted(by_id)}.")
        given[str(k)] = v
    data = []
    for iid, r in given.items():
        if not r:
            raise HlitApiError(f"Aucune ligne fournie pour l'entrée '{iid}'.")
        cols, types, _ = _input_spec(by_id[iid])
        data.append({"num_input": iid, "values": _build_table(r, cols, types)})

    code, body = _request("GET", f"/start-workflow/{key_name}")
    if code != 200 and "already running" not in _message(body):
        raise HlitApiError(f"Démarrage du workflow impossible : {_message(body)}")

    # json.dumps : les colonnes numériques vides sont envoyées en NaN.
    payload = json.dumps({"workflow_id": workflow_id, "timeout": int(timeout_s),
                          "data": data}, ensure_ascii=False)
    while True:
        code, body = _request("POST", "/input-workflow", content=payload.encode("utf-8"),
                              headers={"Content-Type": "application/json"})
        msg = _message(body)
        if code == 200:
            break
        if "already running" in msg:
            # Une exécution est déjà en cours pour ce workflow_id (appel répété
            # par le modèle, ou autre client) : on suit sa sortie.
            out = _poll_output(workflow_id, deadline)
            out["note"] = ("Une exécution était déjà en cours pour ce workflow : "
                           "résultat de cette exécution, pas des lignes fournies.")
            return out
        if code == 202:          # Orange charge encore le workflow
            if time.time() >= deadline:
                return {"status": "starting", "workflow_id": workflow_id,
                        "message": "Le workflow se charge encore : rappelez run_workflow "
                                   "avec les mêmes arguments."}
            time.sleep(POLL_S)
            continue
        raise HlitApiError(f"Envoi des données refusé : {msg}")

    return _poll_output(workflow_id, deadline)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
def get_workflow_result(workflow_id: str) -> dict:
    """Récupère la sortie d'un workflow lancé par run_workflow (attend au plus ~45 s).

    Le résultat ne peut être récupéré qu'une fois : il est supprimé côté API
    une fois lu.

    Args:
        workflow_id: workflow_id renvoyé par run_workflow.
    """
    return _poll_output(workflow_id, time.time() + WAIT_MAX_S)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
def stop_workflow(key_name: str) -> dict:
    """Arrête le processus Orange d'un workflow (l'exécution en cours est perdue).

    Args:
        key_name: nom du workflow (list_workflows).
    """
    code, body = _request("GET", f"/kill-process/{key_name}")
    if code != 200:
        raise HlitApiError(f"Arrêt impossible : {_message(body)}")
    return {"status": "ok", "message": _message(body)}


# ── Lancement ───────────────────────────────────────────────────────────────

def http_app(path="/mcp", host="127.0.0.1"):
    """Application Starlette (Streamable HTTP) avec CORS pour les fronts web
    servis en local (TigerHost sur http://127.0.0.1:8080...)."""
    from starlette.middleware.cors import CORSMiddleware

    app = mcp.streamable_http_app(streamable_http_path=path, host=host)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?",
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["mcp-session-id", "mcp-protocol-version"],
    )
    return app


def main():
    global HLIT_API_URL, HLIT_API_KEY
    parser = argparse.ArgumentParser(description="Serveur MCP devant l'API REST HLIT.")
    parser.add_argument("--stdio", action="store_true",
                        help="Transport stdio (LM Studio, Claude Desktop...) au lieu de HTTP.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--path", default="/mcp")
    parser.add_argument("--api-url", default=HLIT_API_URL, help="URL de l'API REST HLIT.")
    parser.add_argument("--api-key", default=HLIT_API_KEY, help="Clé HLIT-API-Key si l'auth est active.")
    args = parser.parse_args()
    HLIT_API_URL, HLIT_API_KEY = args.api_url.rstrip("/"), args.api_key

    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.stdio:
        mcp.run()
        return
    import uvicorn
    uvicorn.run(http_app(args.path, args.host), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
