# widget_diagnostic_core.py
# ---------------------------------------------------------------------------
# Logique (fonctions) du diagnostic des widgets Orange.
#
#
# API publique :
#   get_registry()
#   get_all_categories(registry=None) -> list[str]
#   run_diagnostic(selected_categories=None, include_packages=True,
#                  progress_callback=None, should_cancel=None) -> (headers, rows)
#   write_rows(path, headers, rows) -> Path            (CSV / XLSX / TAB selon l'extension)
#   rows_to_orange_table(headers, rows) -> Orange Table (si Orange dispo)
#   default_output_name(include_packages=True, ext=".csv") -> str
# ---------------------------------------------------------------------------

import re
import os
import sys
import ast
import csv
import json
import hashlib
import platform
import pkgutil
import importlib
import importlib.util
import importlib.metadata
from datetime import datetime
from pathlib import Path


# ── Constantes ──────────────────────────────────────────────────────────────

STDLIB_MODULES = {
    "os", "sys", "re", "ast", "json", "math", "time", "datetime", "pathlib",
    "collections", "itertools", "functools", "typing", "io", "copy", "hashlib",
    "logging", "argparse", "threading", "multiprocessing", "subprocess",
    "socket", "http", "urllib", "email", "csv", "xml", "html", "traceback",
    "warnings", "weakref", "gc", "inspect", "importlib", "pkgutil", "abc",
    "contextlib", "dataclasses", "enum", "struct", "array", "queue", "heapq",
    "bisect", "string", "textwrap", "difflib", "fnmatch", "glob", "shutil",
    "tempfile", "stat", "platform", "signal", "ctypes", "pickle", "shelve",
    "sqlite3", "configparser", "base64", "binascii", "codecs", "locale",
    "gettext", "uuid", "random", "secrets", "statistics", "decimal", "fractions",
    "numbers", "cmath", "builtins", "__future__", "distutils", "pkg_resources",
    "site", "unittest", "pydoc",
}

INTERNAL_PACKAGES = {"orangecontrib", "orange", "anyqt", "orangewidget"}


# ── Registry ────────────────────────────────────────────────────────────────

def get_registry():
    """Retourne le registry global d'Orange Canvas."""
    from orangecanvas.registry import global_registry
    registry = global_registry
    if callable(registry):
        registry = registry()
    return registry


def get_all_categories(registry=None):
    """Liste triée de toutes les catégories de widgets connues du registry."""
    if registry is None:
        registry = get_registry()
    return sorted({(w.category or "").strip() for w in registry.widgets()})


# ── Normalisation pip ───────────────────────────────────────────────────────

def pip_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def build_import_to_pip_map():
    mapping = {}
    try:
        for mod, dists in importlib.metadata.packages_distributions().items():
            if dists:
                mapping[mod.lower()] = pip_name(dists[0])
    except Exception:
        pass
    return mapping


_IMPORT_TO_PIP = None


def import_to_pip_map():
    """Map import-name -> pip-name, calculée une seule fois (lazy)."""
    global _IMPORT_TO_PIP
    if _IMPORT_TO_PIP is None:
        _IMPORT_TO_PIP = build_import_to_pip_map()
    return _IMPORT_TO_PIP


def module_to_pip(module_name):
    return import_to_pip_map().get(module_name.lower(), pip_name(module_name))


# ── Résolution des fichiers via importlib ───────────────────────────────────

def module_file(module_name):
    """Fichier .py d'un module, sans exécuter le module lui-même (find_spec)."""
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ValueError, ModuleNotFoundError, AttributeError):
        return None
    if spec is None:
        return None
    if spec.origin and spec.origin.endswith(".py"):
        return Path(spec.origin)
    if spec.submodule_search_locations:
        for loc in spec.submodule_search_locations:
            init = Path(loc) / "__init__.py"
            if init.exists():
                return init
    return None


def widget_source_file(desc):
    qn = desc.qualified_name
    for candidate in (qn.rsplit(".", 1)[0], qn):
        f = module_file(candidate)
        if f is not None:
            return f
    return None


def resolve_all_recursive(py_file, visited=None):
    if visited is None:
        visited = set()
    py_file = py_file.resolve()
    if py_file in visited:
        return set()
    visited.add(py_file)

    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return set()

    found_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                root_pkg = n.name.split(".")[0].lower()
                if root_pkg in INTERNAL_PACKAGES:
                    f = module_file(n.name)
                    if f:
                        found_modules |= resolve_all_recursive(f, visited)
                else:
                    found_modules.add(root_pkg)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0 or not node.module:
                continue
            root_pkg = node.module.split(".")[0].lower()
            if root_pkg in INTERNAL_PACKAGES:
                f = module_file(node.module)
                if f:
                    found_modules |= resolve_all_recursive(f, visited)
            else:
                found_modules.add(root_pkg)
    return found_modules


def filter_external(modules):
    return sorted({
        m for m in modules
        if m and m not in STDLIB_MODULES
        and m not in INTERNAL_PACKAGES and not m.startswith("_")
    })


def packages_of(py_file):
    raw = resolve_all_recursive(py_file)
    pkgs = sorted({module_to_pip(m) for m in filter_external(raw)})
    return pkgs


# ── Détection statique d'un widget (AST) ────────────────────────────────────

def ast_widgets(tree):
    """Classes ressemblant à un widget Orange : héritent d'une base finissant
    par 'Widget' ET définissent un attribut de classe name='...'.
    Retourne [(classe, nom_affiché), ...]."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        base_names = [b.id if isinstance(b, ast.Name) else b.attr
                      for b in node.bases if isinstance(b, (ast.Name, ast.Attribute))]
        if not any(bn.endswith("Widget") for bn in base_names):
            continue
        display = None
        for s in node.body:
            if (isinstance(s, ast.Assign) and isinstance(s.value, ast.Constant)
                    and isinstance(s.value.value, str)
                    and any(isinstance(t, ast.Name) and t.id == "name" for t in s.targets)):
                display = s.value.value
                break
        if display:
            out.append((node.name, display))
    return out


# ── Découverte indépendante via entry points 'orange.widgets' ───────────────

def widget_packages():
    """(catégorie, package) déclarés par les add-ons / le cœur d'Orange."""
    try:
        eps = importlib.metadata.entry_points(group="orange.widgets")
    except TypeError:  # API < 3.10
        eps = importlib.metadata.entry_points().get("orange.widgets", [])
    for ep in eps:
        yield ep.name, ep.module


def iter_widget_modules(pkg_name):
    try:
        pkg = importlib.import_module(pkg_name)
    except Exception:
        return
    for info in pkgutil.iter_modules(getattr(pkg, "__path__", []) or [], pkg_name + "."):
        yield info.name


# ── Colonnes de sortie (dynamiques selon les options) ───────────────────────

def _columns_for(include_packages, compare=False):
    """Retourne la liste ordonnée (en-tête, clé_interne) des colonnes."""
    cols = [
        ("Widget_Orange_Name", "name"),
        ("Widget", "widget"),
        ("Catégorie", "category"),
    ]
    if include_packages:
        cols.append(("Package pip", "package"))
        if compare:
            cols.append(("Version lib (réf → actuelle)", "pkg_status"))
    cols.append(("Statut", "statut"))
    if compare:
        cols.append((".py modifié ?", "file_status"))
    cols.append(("Lancer le widget", "launch"))
    return cols


def launch_command(file_path):
    """Commande à coller dans un cmd pour lancer le widget :
    "<python.exe>" "<chemin_du_widget.py>"."""
    if not file_path:
        return ""
    return f'"{sys.executable}" "{file_path}"'


def _make_record(name, widget_label, category, statut, file_path,
                 package="", file_status="", pkg_status=""):
    """Construit un enregistrement complet (dict) pour un widget."""
    if file_path is not None:
        widget = file_path.name
        launch = launch_command(file_path)
    else:
        widget = widget_label if widget_label is not None else ""
        launch = ""
    return {
        "name": name,
        "widget": widget,
        "category": category,
        "package": package,
        "statut": statut,
        "launch": launch,
        "file_status": file_status,
        "pkg_status": pkg_status,
    }


def _project(records, cols):
    """Projette les enregistrements (dicts) sur les colonnes choisies."""
    return [[rec.get(key, "") for _, key in cols] for rec in records]


def _sort_records(records):
    """Tri stable : statut != 'OK' d'abord, en conservant l'ordre interne."""
    return sorted(records, key=lambda r: 0 if (r.get("statut", "") != "OK") else 1)


# ── Scan principal (paramétrable) ───────────────────────────────────────────

def run_diagnostic(selected_categories=None, include_packages=True,
                   reference=None,
                   progress_callback=None, should_cancel=None):
    """
    Lance le diagnostic.

    Paramètres
    ----------
    selected_categories : list[str] | None
        Catégories à analyser. Vide ou None => toutes.
    include_packages : bool
        Si True, calcule (récursivement, AST) les librairies pip de chaque
        widget -> une ligne par (widget, package) [grain fin].
        Si False, une seule ligne par widget, sans analyse des librairies
        [grain grossier, beaucoup plus rapide].
    reference : dict | None
        Si fourni (voir build_reference / load_reference), active la comparaison :
        ajoute les colonnes ".py modifié ?" et "Version lib (réf → actuelle)".
    progress_callback : callable(done, total, message) | None
        Appelé régulièrement pour suivre l'avancement.
    should_cancel : callable() -> bool | None
        Si renvoie True, le scan s'arrête proprement et retourne le partiel.

    Retourne
    --------
    (headers, rows)
        Les widgets dont le statut n'est pas "OK" sont placés en premier.
        La colonne "Lancer le widget" contient la commande
        "<python.exe>" "<chemin_du_widget.py>" à coller dans un cmd.
    """
    compare = reference is not None
    cols = _columns_for(include_packages, compare=compare)
    headers = [h for h, _ in cols]
    records = []

    for w in iter_widgets(selected_categories, progress_callback, should_cancel):
        name = w["name"]
        category = w["category"]
        statut = w["statut"]
        src = w["file_path"]
        qualified = w["qualified"]

        file_status = compare_file(qualified, src, reference) if compare else ""

        if src is None:
            records.append(_make_record(
                name, "(fichier introuvable)", category, statut, None,
                file_status=file_status))
            continue

        if include_packages:
            pkgs = packages_of(src) or ["(aucun)"]
            for pkg in pkgs:
                pkg_status = compare_package(pkg, reference) if compare else ""
                records.append(_make_record(
                    name, None, category, statut, src,
                    package=pkg,
                    file_status=file_status, pkg_status=pkg_status))
        else:
            records.append(_make_record(
                name, None, category, statut, src,
                file_status=file_status))

    records = _sort_records(records)
    return headers, _project(records, cols)


# ── Énumération unifiée des widgets ─────────────────────────────────────────

def iter_widgets(selected_categories=None, progress_callback=None, should_cancel=None):
    """Génère un dict par widget :
        {name, category, statut, file_path (Path|None), qualified}
    Réutilisé par run_diagnostic ET build_reference.
    statut == 'OK' pour les widgets chargés ; sinon raison du problème."""
    registry = get_registry()

    selected = {c.strip().lower() for c in (selected_categories or [])}

    def category_selected(cat):
        return not selected or (cat or "").strip().lower() in selected

    def cancelled():
        return bool(should_cancel) and should_cancel()

    loaded_modules = set()

    phase1 = sorted(registry.widgets(), key=lambda d: (d.category or "", d.name))

    phase2 = []
    for category, pkg_name in widget_packages():
        if not category_selected(category):
            continue
        for modname in iter_widget_modules(pkg_name):
            phase2.append((category, modname))

    total = len(phase1) + len(phase2)
    done = 0

    # --- Phase 1 : widgets chargés (registry) ---
    for desc in phase1:
        if cancelled():
            return
        loaded_modules.add(desc.qualified_name.rsplit(".", 1)[0])
        category = desc.category or "(sans catégorie)"
        done += 1
        if progress_callback:
            progress_callback(done, total, desc.name)
        if not category_selected(category):
            continue

        src = widget_source_file(desc)
        if src is None:
            yield {"name": desc.name, "category": category,
                   "statut": "introuvable", "file_path": None,
                   "qualified": desc.qualified_name}
        else:
            yield {"name": desc.name, "category": category,
                   "statut": "OK", "file_path": src,
                   "qualified": desc.qualified_name}

    # --- Phase 2 : widgets cassés / non chargés ---
    for category, modname in phase2:
        if cancelled():
            return
        done += 1
        if progress_callback:
            progress_callback(done, total, modname)

        if modname in loaded_modules:
            continue
        f = module_file(modname)
        if f is None:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        widgets_found = ast_widgets(tree)
        if not widgets_found:
            continue

        display = widgets_found[0][1]
        try:
            importlib.import_module(modname)
            statut = "non chargé (import OK, absent du registry)"
        except Exception as e:
            statut = f"{type(e).__name__}: {e}"

        yield {"name": display, "category": category,
               "statut": statut, "file_path": f, "qualified": modname}


# ── Référence & comparaison ─────────────────────────────────────────────────

def file_hash(path):
    """SHA-256 d'un fichier, ou None si illisible."""
    if not path:
        return None
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def installed_version(pip_name_):
    """Version installée d'un paquet pip, ou None."""
    if not pip_name_ or pip_name_.startswith("("):
        return None
    try:
        return importlib.metadata.version(pip_name_)
    except Exception:
        return None


def snapshot_packages():
    """Map {pip_name: version} de TOUTES les distributions installées."""
    out = {}
    try:
        for dist in importlib.metadata.distributions():
            try:
                name = pip_name(dist.metadata["Name"])
                out[name] = dist.version
            except Exception:
                continue
    except Exception:
        pass
    return out


def build_reference(selected_categories=None, progress_callback=None, should_cancel=None):
    """Construit une référence : versions pip + hash des .py de widgets.

    Retourne un dict sérialisable JSON :
        {created, machine, python_hash, packages:{...}, files:{qualified:{...}}}
    """
    files = {}
    for w in iter_widgets(selected_categories, progress_callback, should_cancel):
        src = w["file_path"]
        if src is None:
            continue
        qn = w["qualified"]
        if qn in files:
            continue
        files[qn] = {
            "hash": file_hash(src),
            "path": str(src),
            "name": src.name,
            "widget": w["name"],
        }

    return {
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "machine": platform.node(),
        "python_hash": python_hash(),
        "packages": snapshot_packages(),
        "files": files,
    }


def save_reference(path, ref):
    p = Path(path)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(ref, f, ensure_ascii=False, indent=2)
    return p


def load_reference(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Emplacement fixe de la référence : <aait_store>/Parameters/ ─────────────

REFERENCE_FILENAME = "widget_diagnostic_ref.json"

# Surcharge éventuelle : renseigner ici, ou via la variable d'env AAIT_STORE.
AAIT_STORE_OVERRIDE = None


def aait_store_dir():
    """Répertoire du 'aait store' d'Orange.

    Source principale : orangecontrib.AAIT.utils.MetManagement.get_local_store_path()
    (qui crée le dossier au besoin). Replis : AAIT_STORE_OVERRIDE, variable
    d'env AAIT_STORE, puis ~/aait_store — utilisés seulement si AAIT n'est pas
    importable (par ex. en test hors Orange)."""
    if AAIT_STORE_OVERRIDE:
        return Path(AAIT_STORE_OVERRIDE)

    try:
        from orangecontrib.AAIT.utils import MetManagement
        return Path(MetManagement.get_local_store_path())
    except Exception:
        pass

    env = os.environ.get("AAIT_STORE")
    if env:
        return Path(env)

    return Path.home() / "aait_store"


def parameters_dir(create=False):
    """<aait_store>/Parameters. Créé si create=True."""
    d = aait_store_dir() / "Parameters"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def reference_path(create=False):
    """Chemin fixe du fichier de référence."""
    return parameters_dir(create=create) / REFERENCE_FILENAME


def reference_exists():
    try:
        return reference_path().is_file()
    except Exception:
        return False


def save_reference_default(ref):
    """Enregistre la référence à l'emplacement fixe (crée l'arborescence)."""
    return save_reference(reference_path(create=True), ref)


def load_reference_default():
    return load_reference(reference_path())


def default_ref_name():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"diagnostic_ref_{stamp}.json"


def compare_file(qualified, src, reference):
    """Compare le .py courant à la référence. Renvoie un libellé lisible."""
    if src is None:
        return "(fichier introuvable)"
    files = (reference or {}).get("files", {})
    entry = files.get(qualified)
    cur = file_hash(src)
    if entry is None:
        return "nouveau (absent réf)"
    ref_hash = entry.get("hash")
    if cur is None:
        return "(illisible)"
    if ref_hash == cur:
        return "non"
    return "OUI (modifié)"


def compare_package(pip_name_, reference):
    """Compare la version installée d'un paquet à celle de la référence."""
    if not pip_name_ or pip_name_.startswith("("):
        return ""
    ref_pkgs = (reference or {}).get("packages", {})
    ref_ver = ref_pkgs.get(pip_name_)
    cur = installed_version(pip_name_)
    if ref_ver is None and cur is None:
        return "?"
    if ref_ver is None:
        return f"nouvelle (actuelle {cur})"
    if cur is None:
        return f"absente (réf {ref_ver})"
    if cur == ref_ver:
        return f"= {cur}"
    return f"{ref_ver} → {cur}"


# ── Tutoriels : lancement de workflows + comparaison OK/NOK ──────────────────
#
# Mode SERVEUR (comme agentIA, chemin robuste qui évite la duplication) :
#   _ensure_api_running(...)                              -> démarre l'API si besoin
#   expected_input_for_workflow(key, out_tab_input=[])   -> dict d'entrée attendue
#   convert.convert_json_to_orange_data_table(...)       -> Table d'entrée
#   daemonizer_with_input_output(in_data, ip_port, key, temporisation, out=[]) -> out[0] = Table
#   expected_output_for_workflow(key, out_tab_output=[]) -> out[0]["data"] = sortie attendue
#   convert.convert_json_implicite_to_data_table(...)    -> Table attendue
# La clé du workflow (key_name) == champ "name" du tutoriel (confirmé par le
# __main__ de management_workflow_sans_api : key_name = "export_md").
# La comparaison reprend la logique du widget CheckTable (schéma de colonnes).

TUTORIAL_SUBDIR = "linkHTMLWorkflow"
TUTORIAL_FILENAME = "tutorial.json"

TUTORIAL_HEADERS = ["Tutoriel", "Description", "Fichier OWS", "Résultat", "Détail"]


def tutorials_dir():
    return aait_store_dir() / "Parameters" / TUTORIAL_SUBDIR


def tutorial_json_path():
    return tutorials_dir() / TUTORIAL_FILENAME


def tutorial_exists():
    try:
        return tutorial_json_path().is_file()
    except Exception:
        return False


def load_tutorials():
    """Charge la liste des tutoriels depuis tutorial.json.
    Tolère un objet unique ou une liste."""
    p = tutorial_json_path()
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = [data]
    return [e for e in data if isinstance(e, dict)]


def _hlit_modules():
    """Importe tout ce qu'il faut pour le mode serveur (comme agentIA),
    en gérant les deux dispositions de packages HLIT_dev."""
    try:
        from orangecontrib.HLIT_dev.remote_server_smb import (
            convert, server_uvicorn, management_workflow_sans_api,
        )
        from orangecontrib.HLIT_dev.utils import hlit_python_api
        from orangecontrib.HLIT_dev.utils.hlit_python_api import (
            daemonizer_with_input_output,
        )
    except Exception:
        from Orange.widgets.orangecontrib.HLIT_dev.remote_server_smb import (
            convert, server_uvicorn, management_workflow_sans_api,
        )
        from Orange.widgets.orangecontrib.HLIT_dev.utils import hlit_python_api
        from Orange.widgets.orangecontrib.HLIT_dev.utils.hlit_python_api import (
            daemonizer_with_input_output,
        )
    return (convert, server_uvicorn, management_workflow_sans_api,
            hlit_python_api, daemonizer_with_input_output)


def _ensure_api_running(hlit_api, server_uvicorn, ip="127.0.0.1", port=8000,
                        wait_s=40):
    """S'assure que le serveur API tourne : le démarre si besoin, puis attend
    que le port réponde (jusqu'à wait_s secondes). Retourne True si prêt."""
    import time
    if server_uvicorn.is_port_in_use(ip, port, timeout=5):
        return True
    hlit_api.start_api_in_new_terminal()
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if server_uvicorn.is_port_in_use(ip, port, timeout=2):
            return True
        time.sleep(1.0)
    return False


def api_is_running(ip_port="127.0.0.1:8000"):
    """True si le serveur API répond déjà sur ip:port."""
    try:
        _, server_uvicorn, _, _, _ = _hlit_modules()
    except Exception:
        return False
    ip = ip_port.split(":")[0] if ":" in ip_port else "127.0.0.1"
    port = int(ip_port.split(":")[1]) if ":" in ip_port else 8000
    try:
        return bool(server_uvicorn.is_port_in_use(ip, port, timeout=5))
    except Exception:
        return False


def stop_api(ip_port="127.0.0.1:8000"):
    """Arrête le serveur API (hlit_python_api.exit_server). Retourne le code."""
    try:
        _, _, _, hlit_api, _ = _hlit_modules()
    except Exception:
        return 1
    try:
        return hlit_api.exit_server(ip_port)
    except Exception:
        return 1


def thread_management_module():
    """Accès à AAIT thread_management (pour lancer run_tutorial dans un thread)."""
    try:
        from orangecontrib.AAIT.utils import thread_management
    except Exception:
        from Orange.widgets.orangecontrib.AAIT.utils import thread_management
    return thread_management


def _met_management():
    """Importe MetManagement en gérant les deux dispositions de packages."""
    try:
        from orangecontrib.AAIT.utils import MetManagement
    except Exception:
        from Orange.widgets.orangecontrib.AAIT.utils import MetManagement
    return MetManagement


def _compare_cols(cols_ref, cols_data):
    """Logique reprise telle quelle du widget CheckTable : compare deux listes
    de colonnes (dicts {name, kind, var_type, ...}) comme des ensembles.
    Retourne (only_ref, only_data) :
      - only_ref  : colonnes attendues (référence) absentes des données
      - only_data : colonnes présentes dans les données mais pas en référence."""
    set_ref = {tuple(sorted(d.items())) for d in cols_ref}
    set_data = {tuple(sorted(d.items())) for d in cols_data}
    only_ref = [dict(t) for t in (set_ref - set_data)]
    only_data = [dict(t) for t in (set_data - set_ref)]
    return only_ref, only_data


def compare_tables(out_data, expected,
                   check_number_of_line=False, allow_extra_column=False):
    """Compare la sortie d'un workflow à la sortie attendue, avec la MÊME
    logique que le widget CheckTable : comparaison du schéma de colonnes via
    MetManagement.describe_orange_table (référence = sortie attendue), plus
    l'option facultative de vérification du nombre de lignes.
    Renvoie (ok: bool, detail: str)."""
    if out_data is None or expected is None:
        return False, "table manquante (sortie ou attendu None)"

    Met = _met_management()
    ref = Met.describe_orange_table(expected)   # référence = sortie attendue
    cur = Met.describe_orange_table(out_data)   # données à vérifier
    if cur is None and ref is None:
        return False, "describe_orange_table a échoué (sortie produite ET attendue illisibles)"
    if cur is None:
        return False, "describe_orange_table a échoué (sortie produite illisible)"
    if ref is None:
        return False, "describe_orange_table a échoué (sortie attendue illisible)"

    ref_nb, ref_cols = ref[0], ref[1]
    cur_nb, cur_cols = cur[0], cur[1]

    if check_number_of_line and cur_nb != int(ref_nb):
        return False, f"number of line invalid {cur_nb}!={ref_nb}"

    only_ref, only_data = _compare_cols(ref_cols, cur_cols)
    if only_ref:
        if only_data:
            return False, ("missing column" + str(only_ref)
                           + " ++++ column not in reference -> " + str(only_data))
        return False, "missing column" + str(only_ref)
    if only_data and not allow_extra_column:
        return False, "column not in reference -> " + str(only_data)

    return True, "OK"


def _purge_workflow_state(mws, key_name):
    """Supprime le verrou admin résiduel <admin>/<key_name>.txt avant de lancer
    (exactement agentIA.purge_locker)."""
    try:
        Met = _met_management()
        adm = Met.get_api_local_folder_admin()
        lock = adm + key_name + ".txt"
        if os.path.exists(lock):
            os.remove(lock)
    except Exception:
        pass


def run_tutorial(entry, ip_port="127.0.0.1:8000", poll_sleep=0.3):
    """Exécute UN tutoriel en mode serveur (comme agentIA : API + daemonizer),
    puis compare la sortie à l'attendu. Renvoie toujours un dict, jamais
    d'exception : {name, description, ows_file, status: OK|NOK|ERREUR, detail}."""
    key_name = entry.get("key_name") or entry.get("name") or ""
    result = {
        "name": key_name,
        "description": entry.get("description", ""),
        "ows_file": entry.get("ows_file", ""),
        "status": "ERREUR",
        "detail": "",
    }
    if not key_name:
        result["detail"] = "champ 'name'/'key_name' absent"
        return result

    try:
        convert, server_uvicorn, mws, hlit_api, daemonizer = _hlit_modules()
    except Exception as e:
        result["detail"] = f"API HLIT_dev indisponible : {e}"
        return result

    # 0) Purge du verrou résiduel (agentIA.purge_locker)
    _purge_workflow_state(mws, key_name)

    # 1) S'assurer que le serveur API tourne
    ip = ip_port.split(":")[0] if ":" in ip_port else "127.0.0.1"
    port = int(ip_port.split(":")[1]) if ":" in ip_port else 8000
    if not _ensure_api_running(hlit_api, server_uvicorn, ip=ip, port=port):
        result["detail"] = "serveur API indisponible (démarrage/attente échoué)"
        return result

    # 2) Entrée attendue -> Table (comme agentIA.set_expected_input)
    out_tab_input = []
    try:
        rc = mws.expected_input_for_workflow(key_name, out_tab_input=out_tab_input)
    except Exception as e:
        result["detail"] = f"lecture entrée attendue : {e}"
        return result
    if rc != 0 or not out_tab_input:
        result["status"] = "NOK"
        result["detail"] = f"lecture entrée attendue échouée (rc={rc})"
        return result
    try:
        in_data = convert.convert_json_to_orange_data_table(out_tab_input[0]["data"][0])
    except Exception as e:
        result["detail"] = f"conversion entrée attendue : {e}"
        return result

    # 3) Exécution via le daemonizer (mode serveur, comme agentIA._run_daemonizer)
    out_tab_output = []
    try:
        rc = daemonizer(in_data, ip_port, key_name,
                        temporisation=poll_sleep, out_tab_output=out_tab_output)
    except Exception as e:
        result["detail"] = f"exécution (daemonizer) : {e}"
        return result
    if rc != 0 or not out_tab_output:
        result["status"] = "NOK"
        result["detail"] = f"exécution échouée (rc={rc})"
        _purge_workflow_state(mws, key_name)
        return result
    out_data = out_tab_output[0]

    # Normalisation : out_data devrait déjà être une Table ; sinon on convertit.
    if out_data is None:
        result["status"] = "NOK"
        result["detail"] = "sortie produite vide (None)"
        return result
    try:
        from Orange.data import Table as _OrangeTable
    except Exception:
        _OrangeTable = None
    if _OrangeTable is not None and not isinstance(out_data, _OrangeTable):
        try:
            out_data = convert.convert_json_implicite_to_data_table(out_data)
        except Exception as e:
            result["detail"] = f"conversion sortie produite : {e}"
            return result

    # 4) Sortie attendue -> Table (comme agentIA / OutputInterface).
    data_output = []
    try:
        rc = mws.expected_output_for_workflow(key_name, out_tab_output=data_output)
        if rc != 0 or not data_output:
            result["status"] = "NOK"
            result["detail"] = f"lecture sortie attendue échouée (rc={rc})"
            return result
        expected = convert.convert_json_implicite_to_data_table(data_output[0]["data"])
    except Exception as e:
        result["detail"] = f"sortie attendue : {e}"
        return result

    # 5) Comparaison (logique CheckTable)
    ok, detail = compare_tables(out_data, expected)
    result["status"] = "OK" if ok else "NOK"
    result["detail"] = detail
    return result


def run_all_tutorials(entries, progress_callback=None, should_cancel=None, on_result=None):
    """Exécute une liste de tutoriels séquentiellement.
    on_result(index, result) est appelé après chaque tuto (pour l'UI)."""
    results = []
    total = len(entries)
    for i, entry in enumerate(entries):
        if should_cancel and should_cancel():
            break
        if progress_callback:
            progress_callback(i + 1, total, entry.get("name", ""))
        res = run_tutorial(entry)
        results.append(res)
        if on_result:
            on_result(i, res)
    return results


def tutorial_results_to_rows(results):
    """(headers, rows) exportables (CSV/XLSX) à partir des résultats."""
    rows = [[r.get("name", ""), r.get("description", ""), r.get("ows_file", ""),
             r.get("status", ""), r.get("detail", "")] for r in results]
    return list(TUTORIAL_HEADERS), rows


def default_tutorial_output_name(ext=".xlsx"):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"tutoriels_resultats_{stamp}{ext}"


# ── Métadonnées du test ─────────────────────────────────────────────────────

_PYTHON_HASH = None


def python_hash():
    """SHA-256 de l'exécutable Python courant (identifie l'environnement).
    Calculé une seule fois par session. Repli sur un hash de
    (exécutable + version) si le binaire n'est pas lisible."""
    global _PYTHON_HASH
    if _PYTHON_HASH is not None:
        return _PYTHON_HASH
    try:
        h = hashlib.sha256()
        with open(sys.executable, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        _PYTHON_HASH = h.hexdigest()
    except Exception:
        base = f"{sys.executable}|{sys.version}"
        _PYTHON_HASH = hashlib.sha256(base.encode("utf-8", "replace")).hexdigest()
    return _PYTHON_HASH


def collect_metadata(when=None):
    """Métadonnées du test, sous forme de liste ordonnée (clé, valeur)."""
    when = when or datetime.now()
    return [
        ("Date/heure test", when.strftime("%Y-%m-%d %H:%M:%S")),
        ("Machine", platform.node()),
        ("Python (exécutable)", sys.executable),
        ("Python (version)", platform.python_version()),
        ("Hash Python", python_hash()),
    ]


# ── Écriture des résultats ──────────────────────────────────────────────────

def _write_delimited(path, headers, rows, delimiter):
    path = Path(path)
    # utf-8-sig => ouverture propre dans Excel (accents)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=delimiter)
        w.writerow(headers)
        w.writerows(rows)
    return path


def _write_xlsx(path, headers, rows, metadata=None):
    try:
        from openpyxl import Workbook
    except Exception as e:
        raise RuntimeError(
            "Le format .xlsx nécessite le paquet 'openpyxl'. "
            "Installe-le (pip install openpyxl) ou choisis un fichier .csv."
        ) from e
    path = Path(path)
    wb = Workbook()
    ws = wb.active
    ws.title = "Diagnostic"
    ws.append(list(headers))
    for r in rows:
        ws.append(list(r))

    if metadata:
        ms = wb.create_sheet("Métadonnées")
        ms.append(["Clé", "Valeur"])
        for k, v in metadata:
            ms.append([k, "" if v is None else str(v)])

    wb.save(path)
    return path


def write_rows(path, headers, rows, metadata=None):
    """Écrit headers+rows selon l'extension : .xlsx, .tab/.tsv (tabulation),
    sinon CSV (séparateur ';').

    metadata : liste (clé, valeur) ou None.
        - .xlsx : écrites sur une feuille 'Métadonnées' dédiée.
        - .csv/.tab : non injectées (pour ne pas casser le tableau) ; un
          fichier '<nom>.meta.csv' à côté est écrit si metadata est fourni.
    """
    p = Path(path)
    ext = p.suffix.lower()

    if ext in (".xlsx", ".xlsm"):
        return _write_xlsx(p, headers, rows, metadata)

    if ext in (".tab", ".tsv"):
        out = _write_delimited(p, headers, rows, "\t")
    else:
        out = _write_delimited(p, headers, rows, ";")

    # Pour les formats texte : métadonnées dans un sidecar séparé.
    if metadata:
        side = p.with_suffix(p.suffix + ".meta.csv")
        with open(side, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Clé", "Valeur"])
            for k, v in metadata:
                w.writerow([k, "" if v is None else str(v)])
    return out


def default_output_name(include_packages=True, ext=".csv"):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    grain = "detaille" if include_packages else "synthese"
    return f"diagnostic_widgets_{grain}_{stamp}{ext}"


# ── Sortie Orange (optionnelle) ─────────────────────────────────────────────

def rows_to_orange_table(headers, rows):
    """Construit une Orange Table (metas = colonnes texte). Utile si on veut
    réinjecter le résultat dans le Canvas."""
    import numpy as np
    from Orange.data import Table, Domain, StringVariable

    domain = Domain([], metas=[StringVariable(h) for h in headers])
    metas = np.array(rows, dtype=object) if rows else np.empty((0, len(headers)), dtype=object)
    return Table.from_numpy(domain, np.empty((len(rows), 0)), metas=metas)
