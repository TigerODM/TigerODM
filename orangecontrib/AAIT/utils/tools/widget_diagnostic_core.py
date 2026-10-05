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

import os
import re
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
    """Map {nom_import: nom_pip}.

    1) API standard packages_distributions() (fiable quand elle connaît le module).
    2) Complément via le top_level.txt de chaque distribution : rattrape les cas
       où l'API ne liste pas le module (Orange -> orange3, add-ons, etc.).
       setdefault() garantit qu'on n'écrase jamais l'info de l'étape 1.
    """
    mapping = {}
    try:
        for mod, dists in importlib.metadata.packages_distributions().items():
            if dists:
                mapping[mod.lower()] = pip_name(dists[0])
    except Exception:
        pass
    try:
        for dist in importlib.metadata.distributions():
            try:
                dist_name = pip_name(dist.metadata["Name"])
            except Exception:
                continue
            tops = []
            try:
                tl = dist.read_text("top_level.txt")
                if tl:
                    tops = [t.strip() for t in tl.splitlines() if t.strip()]
            except Exception:
                pass
            for top in (tops or [dist_name]):
                mapping.setdefault(top.lower(), dist_name)
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

# Source de vérité unique : clé interne -> libellé affiché.
# _columns_for ET build_summary s'y réfèrent, pour qu'un renommage ici se
# répercute partout sans casser le récapitulatif.
COLUMN_LABELS = {
    "name": "Widget",
    "widget": "Fichier .py",
    "category": "Catégorie",
    "package": "Package pip",
    "pkg_status": "Version lib (réf → actuelle)",
    "statut": "Statut",
    "file_status": "Modifié vs réf.",
    "launch": "Lancer le widget",
    "widget_key": "Identifiant widget",
    "coverage": "Couvert par (workflows)",
    "variant": "Version",
}


def _col(key):
    """(libellé, clé) pour une colonne, d'après COLUMN_LABELS."""
    return (COLUMN_LABELS[key], key)


def _columns_for(include_packages, compare=False, coverage=False, variant=False):
    """Retourne la liste ordonnée (en-tête, clé_interne) des colonnes."""
    cols = [_col("name"), _col("widget"), _col("category")]
    if variant:
        cols.append(_col("variant"))
    if include_packages:
        cols.append(_col("package"))
        if compare:
            cols.append(_col("pkg_status"))
    cols.append(_col("statut"))
    if compare:
        cols.append(_col("file_status"))
    if coverage:
        cols.append(_col("coverage"))
        cols.append(_col("widget_key"))
    cols.append(_col("launch"))
    return cols


def launch_command(file_path):
    """Commande à coller dans un cmd pour lancer le widget :
    "<python.exe>" "<chemin_du_widget.py>"."""
    if not file_path:
        return ""
    return f'"{sys.executable}" "{file_path}"'


def _make_record(name, widget_label, category, statut, file_path,
                 package="", file_status="", pkg_status="",
                 widget_key_="", coverage="", variant=""):
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
        "widget_key": widget_key_,
        "coverage": coverage,
        "variant": variant,
    }


def _project(records, cols):
    """Projette les enregistrements (dicts) sur les colonnes choisies."""
    return [[rec.get(key, "") for _, key in cols] for rec in records]


def _sort_records(records):
    """Tri stable : statut != 'OK' d'abord, en conservant l'ordre interne."""
    return sorted(records, key=lambda r: 0 if (r.get("statut", "") != "OK") else 1)


# ── Versions prod / dev des widgets ─────────────────────────────────────────
#
# Sur les machines de dev, un même widget peut exister en deux exemplaires :
#   - prod : site-packages/orangecontrib/<ADDON>/widgets/<fichier>.py
#   - dev  : site-packages/Orange/widgets/orangecontrib/<ADDON>/widgets/<fichier>.py
# Seul l'emplacement Orange/widgets/orangecontrib identifie une version dev ;
# le nom de l'add-on n'est pas pris en compte. Ils partagent nom affiché et catégorie : sans distinction, le
# récapitulatif les fusionnait en un seul widget et ne gardait le statut .py
# que du premier rencontré. Les tutoriels couvrent les widgets de PROD.

DEV_IGNORE = "ignore"       # les versions dev sont exclues du diagnostic
DEV_SEPARATE = "separate"   # prod et dev sont listées séparément (colonne Version)

_RE_DEV_PATH = re.compile(r"(^|[\\/])orange[\\/]widgets[\\/]orangecontrib[\\/]", re.IGNORECASE)


def dev_widgets_dir():
    """Dossier où vivent les versions dev : <site-packages>/Orange/widgets/orangecontrib.
    Localisé via le package Orange, sans l'importer. None si introuvable."""
    try:
        spec = importlib.util.find_spec("Orange")
    except Exception:
        return None
    if spec is None or not spec.origin:
        return None
    return Path(spec.origin).parent / "widgets" / "orangecontrib"


def has_dev_widgets():
    """True si au moins un add-on de dev contient des widgets, c.-à-d. un
    fichier .py (hors __init__) dans Orange/widgets/orangecontrib/<ADDON>/widgets.
    Vérification rapide sur le disque, sans import ni scan du registry."""
    d = dev_widgets_dir()
    try:
        if d is None or not d.is_dir():
            return False
        for addon in d.iterdir():
            w = addon / "widgets"
            if addon.is_dir() and w.is_dir():
                if any(f.name != "__init__.py" for f in w.glob("*.py")):
                    return True
    except Exception:
        return False
    return False


def widget_variant(qualified=None, file_path=None):
    """'dev' ou 'prod' d'après le chemin du .py (prioritaire) ou le nom qualifié."""
    if file_path:
        sp = str(file_path)
        return "dev" if _RE_DEV_PATH.search(sp) else "prod"
    q = str(qualified or "")
    if q.startswith("Orange.widgets.orangecontrib."):
        return "dev"
    return "prod"


# ── Scan principal (paramétrable) ───────────────────────────────────────────

def run_diagnostic(selected_categories=None, include_packages=True,
                   reference=None,
                   progress_callback=None, should_cancel=None,
                   coverage=None, dev_mode=DEV_SEPARATE):
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
    coverage : dict | None
        Résultat de load_coverage(). Si fourni, ajoute les colonnes
        "Couvert par (workflows)" et "Identifiant widget" (via tested_widgets).
        Seules les versions PROD sont rattachées aux tutoriels.
    dev_mode : DEV_IGNORE | DEV_SEPARATE
        DEV_IGNORE : les versions dev (Orange.widgets.orangecontrib…) sont
        exclues. DEV_SEPARATE : elles sont gardées, avec une colonne "Version"
        (prod/dev) pour les distinguer.

    Retourne
    --------
    (headers, rows)
        Les widgets dont le statut n'est pas "OK" sont placés en premier.
        La colonne "Lancer le widget" contient la commande
        "<python.exe>" "<chemin_du_widget.py>" à coller dans un cmd.
    """
    compare = reference is not None
    with_cov = coverage is not None
    separate = dev_mode == DEV_SEPARATE
    cols = _columns_for(include_packages, compare=compare, coverage=with_cov,
                        variant=separate)
    headers = [h for h, _ in cols]
    records = []

    for w in iter_widgets(selected_categories, progress_callback, should_cancel):
        name = w["name"]
        category = w["category"]
        statut = w["statut"]
        src = w["file_path"]
        qualified = w["qualified"]
        variant = widget_variant(qualified, src)
        if variant == "dev" and not separate:
            continue

        file_status = compare_file(qualified, src, reference) if compare else ""
        wkey, cov = "", ""
        if with_cov:
            wkey = widget_key(qualified, src) or ""
            if variant == "prod":          # les tutos couvrent la prod
                cov = COVERAGE_SEP.join(coverage_for(coverage, wkey))
        extra = {"widget_key_": wkey, "coverage": cov, "variant": variant}

        if src is None:
            records.append(_make_record(
                name, "(fichier introuvable)", category, statut, None,
                file_status=file_status, **extra))
            continue

        if include_packages:
            pkgs = packages_of(src) or ["(aucun)"]
            for pkg in pkgs:
                pkg_status = compare_package(pkg, reference) if compare else ""
                records.append(_make_record(
                    name, None, category, statut, src,
                    package=pkg,
                    file_status=file_status, pkg_status=pkg_status, **extra))
        else:
            records.append(_make_record(
                name, None, category, statut, src,
                file_status=file_status, **extra))

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


def reference_info():
    """(créée_le, machine, nb_fichiers) de la référence, ou None si absente/illisible."""
    try:
        if not reference_exists():
            return None
        ref = load_reference_default()
        return (ref.get("created", "?"), ref.get("machine", "?"), len(ref.get("files", {})))
    except Exception:
        return None


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
        return "(hors pip / local)"
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

WORKFLOW_HEADERS_TAIL = ["Description", "Fichier OWS", "Résultat", "Détail", "Durée (s)",
                         "Widgets testés", "À relancer (widget modifié)"]


def workflow_headers(is_tutorial=True):
    """En-têtes de la table / de l'export : 'Tutoriel' pour tutorial.json,
    'Nom' pour les autres batchs (qui ne sont pas des tutoriels)."""
    return ["Tutoriel" if is_tutorial else "Nom"] + list(WORKFLOW_HEADERS_TAIL)


TUTORIAL_HEADERS = workflow_headers(True)


def tutorials_dir():
    return aait_store_dir() / "Parameters" / TUTORIAL_SUBDIR


def tutorial_json_path():
    return tutorials_dir() / TUTORIAL_FILENAME


def tutorial_exists():
    try:
        return tutorial_json_path().is_file()
    except Exception:
        return False


def load_tutorials(path=None):
    """Charge la liste des workflows depuis un fichier JSON de batch.
    Par défaut : tutorial.json. Tolère un objet unique ou une liste."""
    p = Path(path) if path else tutorial_json_path()
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = [data]
    return [e for e in data if isinstance(e, dict)]


def _is_workflow_batch(entries):
    """True si la liste ressemble à un batch de workflows exploitable par
    run_tutorial (au moins une entrée avec 'name' ou 'key_name')."""
    return any(e.get("name") or e.get("key_name") for e in entries)


def list_workflow_batches(include_tutorial=False):
    """Liste les autres fichiers JSON de batch présents à côté de tutorial.json.

    Renvoie (batches, skipped) :
      - batches : liste de dicts {path: Path, label: str, count: int}, triée
        par nom de fichier (tutorial.json exclu sauf include_tutorial=True) ;
      - skipped : liste de (nom_fichier, raison) pour les JSON ignorés
        (illisibles ou sans entrée 'name'/'key_name')."""
    batches, skipped = [], []
    try:
        d = tutorials_dir()
    except Exception:
        return batches, skipped
    if not d.is_dir():
        return batches, skipped
    for p in sorted(d.glob("*.json"), key=lambda x: x.name.lower()):
        if not p.is_file():
            continue
        if p.name.lower() == TUTORIAL_FILENAME.lower() and not include_tutorial:
            continue
        try:
            entries = load_tutorials(p)
        except Exception as e:
            skipped.append((p.name, f"illisible : {e}"))
            continue
        if not _is_workflow_batch(entries):
            skipped.append((p.name, "aucune entrée 'name'/'key_name'"))
            continue
        batches.append({"path": p, "label": p.stem, "count": len(entries)})
    return batches, skipped


def _hlit_modules():
    """Importe tout ce qu'il faut pour le mode serveur (comme agentIA),
    en gérant les deux dispositions de packages HLIT."""
    try:
        from orangecontrib.HLIT.remote_server_smb import (
            convert, server_uvicorn, management_workflow_sans_api,
        )
        from orangecontrib.HLIT.utils import hlit_python_api
        from orangecontrib.HLIT.utils.hlit_python_api import (
            daemonizer_with_input_output,
        )
    except Exception:
        from Orange.widgets.orangecontrib.HLIT.remote_server_smb import (
            convert, server_uvicorn, management_workflow_sans_api,
        )
        from Orange.widgets.orangecontrib.HLIT.utils import hlit_python_api
        from Orange.widgets.orangecontrib.HLIT.utils.hlit_python_api import (
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
    """Exécute UN workflow (tutoriel ou batch) et mesure sa durée.
    Renvoie toujours un dict, jamais d'exception :
    {name, description, ows_file, status: OK|NOK|ERREUR, detail, duration_s, …}."""
    import time
    t0 = time.monotonic()
    try:
        res = _run_tutorial_impl(entry, ip_port=ip_port, poll_sleep=poll_sleep)
    except Exception as e:   # filet de sécurité : jamais d'exception vers l'UI
        res = {"name": entry.get("key_name") or entry.get("name") or "",
               "description": entry.get("description", ""),
               "ows_file": entry.get("ows_file", ""), "status": "ERREUR",
               "detail": f"exception inattendue : {e}",
               "tested_widgets": ", ".join(declared_widgets(entry))}
    res["duration_s"] = round(time.monotonic() - t0, 1)
    return res


def _run_tutorial_impl(entry, ip_port="127.0.0.1:8000", poll_sleep=0.3):
    """Exécute UN workflow en mode serveur (comme agentIA : API + daemonizer),
    puis compare la sortie à l'attendu."""
    key_name = entry.get("key_name") or entry.get("name") or ""
    result = {
        "name": key_name,
        "description": entry.get("description", ""),
        "ows_file": entry.get("ows_file", ""),
        "status": "ERREUR",
        "detail": "",
        "tested_widgets": ", ".join(declared_widgets(entry)),
    }
    if not key_name:
        result["detail"] = "champ 'name'/'key_name' absent"
        return result

    try:
        convert, server_uvicorn, mws, hlit_api, daemonizer = _hlit_modules()
    except Exception as e:
        result["detail"] = f"API HLIT indisponible : {e}"
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


def tutorial_results_to_rows(results, is_tutorial=True):
    """(headers, rows) exportables (CSV/XLSX) à partir des résultats."""
    rows = [[r.get("name", ""), r.get("description", ""), r.get("ows_file", ""),
             r.get("status", ""), r.get("detail", ""), r.get("duration_s", ""),
             r.get("tested_widgets", ""), r.get("rerun", "")] for r in results]
    return workflow_headers(is_tutorial), rows


def resolve_ows_path(entry):
    """Chemin absolu du .ows d'une entrée, ou (None, [chemins essayés]).
    'ows_file' est relatif (ex. 'Tutorial/x.ows') : on essaie les dossiers
    plausibles du store AAIT."""
    rel = str(entry.get("ows_file") or "").strip()
    if not rel:
        return None, []
    p = Path(rel)
    if p.is_absolute():
        return (p if p.is_file() else None), [p]
    tried = []
    bases = []
    try:
        bases += [tutorials_dir(), aait_store_dir() / "Parameters", aait_store_dir()]
    except Exception:
        pass
    for b in bases:
        c = b / rel
        tried.append(c)
        if c.is_file():
            return c, tried
    return None, tried


def default_tutorial_output_name(ext=".xlsx", prefix="tutoriels"):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = re.sub(r"[^\w\-]+", "_", str(prefix or "tutoriels")).strip("_") or "tutoriels"
    return f"{prefix}_resultats_{stamp}{ext}"


# ── Couverture des widgets par les tutoriels (champ tested_widgets) ─────────
#
# Chaque entrée d'un JSON de batch peut déclarer :
#   "tested_widgets": ["orangecontrib.IO4IT.widgets.OWExportMarkdown", ...]
# (liste ou chaîne seule). Formats acceptés pour un identifiant :
#   - module    : orangecontrib.<ADDON>.widgets.<fichier>
#   - qualifié  : orangecontrib.<ADDON>.widgets.<fichier>.<Classe>
#   - préfixé   : Orange.widgets.orangecontrib.<ADDON>.widgets.<fichier>[.<Classe>]
# Tous sont ramenés à une clé normalisée "<ADDON>.<fichier>". Le nom de
# l'add-on est conservé tel quel (HLIT et HLIT_dev sont deux add-ons distincts).

TESTED_FIELD = "tested_widgets"

_RE_KEY_DOTTED = re.compile(
    r"(?:^|\.)orangecontrib\.([A-Za-z0-9_]+?)\.widgets\.([A-Za-z0-9_\-]+)")
_RE_KEY_PATH = re.compile(
    r"orangecontrib[\\/]([^\\/]+?)[\\/]widgets[\\/]([^\\/]+)\.py$",
    re.IGNORECASE)


def widget_key(qualified=None, file_path=None):
    """Clé normalisée '<ADDON>.<fichier>' d'un widget, ou None.
    Le chemin du .py est prioritaire (indépendant du nom de classe)."""
    if file_path:
        m = _RE_KEY_PATH.search(str(file_path))
        if m:
            return f"{m.group(1)}.{m.group(2)}"
    if qualified:
        m = _RE_KEY_DOTTED.search(str(qualified).strip())
        if m:
            return f"{m.group(1)}.{m.group(2)}"
    return None


def declared_widgets(entry):
    """Identifiants bruts déclarés par une entrée (liste ou chaîne tolérée)."""
    v = entry.get(TESTED_FIELD) if isinstance(entry, dict) else None
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return []
    return [str(x).strip() for x in v if str(x).strip()]


def load_coverage(include_batches=False):
    """Construit la table de couverture à partir de tutorial.json
    (+ des autres batchs si include_batches).

    Retourne un dict :
      sources     : [nom_fichier, ...] effectivement lus
      errors      : [(nom_fichier, message), ...]
      by_widget   : {clé_minuscule: [libellé_tuto, ...]}
      declared    : [{label, source, tuto, raw, key}, ...]  (une ligne / id)
      without     : [libellé_tuto, ...]  entrées sans tested_widgets
      invalid     : [(libellé_tuto, raw), ...] identifiants non reconnus
      n_entries   : nombre d'entrées lues
    Libellé = "Tutoriel : <nom>" pour tutorial.json, "Batch <fichier> : <nom>"
    pour les autres batchs (les batchs ne sont pas des tutoriels)."""
    cov = {"sources": [], "errors": [], "by_widget": {}, "declared": [],
           "without": [], "invalid": [], "n_entries": 0}

    files = []
    try:
        if tutorial_exists():
            files.append((tutorial_json_path(), True))
    except Exception:
        pass
    if include_batches:
        try:
            batches, _ = list_workflow_batches()
            files += [(b["path"], False) for b in batches]
        except Exception as e:
            cov["errors"].append(("(autres batchs)", str(e)))

    for path, is_tuto in files:
        try:
            entries = load_tutorials(path)
        except Exception as e:
            cov["errors"].append((Path(path).name, str(e)))
            continue
        cov["sources"].append(Path(path).name)
        for e in entries:
            name = str(e.get("key_name") or e.get("name") or "").strip()
            if not name:
                continue
            cov["n_entries"] += 1
            label = workflow_label(name, None if is_tuto else Path(path).stem)
            ids = declared_widgets(e)
            if not ids:
                cov["without"].append(label)
                continue
            for raw in ids:
                k = widget_key(raw)
                cov["declared"].append({"label": label, "source": Path(path).name,
                                        "tuto": name, "raw": raw, "key": k or ""})
                if not k:
                    cov["invalid"].append((label, raw))
                    continue
                lst = cov["by_widget"].setdefault(k.lower(), [])
                if label not in lst:
                    lst.append(label)
    return cov


COVERAGE_SEP = " ; "

# Texte affiché partout où une information dépend de la comparaison à la
# référence (colonne « Modifié vs réf. », workflows à relancer…).
RERUN_UNAVAILABLE = "non calculé — comparaison à la référence inactive"


def workflow_label(name, batch_stem=None):
    """Libellé affiché d'un workflow : tutoriel ou batch."""
    return f"Tutoriel : {name}" if batch_stem is None else f"Batch {batch_stem} : {name}"


def coverage_for(coverage, key):
    """Libellés des tutos couvrant le widget de clé `key`."""
    if not coverage or not key:
        return []
    return list(coverage.get("by_widget", {}).get(key.lower(), []))


def coverage_report(headers, rows, coverage=None, filtered=False):
    """Statistiques de couverture à partir des lignes du diagnostic.

    Retourne un dict ou None si les colonnes de couverture sont absentes :
      total, covered, uncovered (listes de (nom, catégorie)),
      covered_not_ok [(nom, statut, tutos)], multi [(nom, tutos)],
      by_category {cat: [couverts, total]}, to_rerun [(tuto, [widgets])],
      orphans [(libellé, raw)], invalid, without, sources, filtered."""
    lab = COLUMN_LABELS
    if lab["coverage"] not in headers or lab["widget_key"] not in headers:
        return None
    ix = {k: (headers.index(lab[k]) if lab[k] in headers else None)
          for k in ("name", "category", "statut", "file_status", "coverage", "widget_key",
                    "variant")}

    def cell(row, k):
        i = ix[k]
        return "" if i is None or i >= len(row) or row[i] is None else str(row[i]).strip()

    # Dédoublonnage par clé widget (grain fin = plusieurs lignes / widget).
    # Seules les versions PROD comptent : les tutos couvrent la prod.
    units = {}
    for i, row in enumerate(rows):
        if cell(row, "variant") == "dev":
            continue
        k = cell(row, "widget_key").lower() or f"#row{i}"
        u = units.setdefault(k, {"name": cell(row, "name"), "cat": cell(row, "category"),
                                 "status": cell(row, "statut"), "file": cell(row, "file_status"),
                                 "tutos": cell(row, "coverage")})
        if u["status"].upper() != "OK" and cell(row, "statut").upper() == "OK":
            u["status"] = "OK"   # au moins une installation saine
        if not u["file"]:
            u["file"] = cell(row, "file_status")

    def tutos(u):
        return [t.strip() for t in u["tutos"].split(COVERAGE_SEP.strip()) if t.strip()]

    rep_ = {"total": len(units), "covered": [], "uncovered": [], "covered_not_ok": [],
            "multi": [], "by_category": {}, "to_rerun": {}, "filtered": filtered,
            "compare": ix["file_status"] is not None,   # « à relancer » calculable ?
            "orphans": [], "invalid": [], "without": [], "sources": []}
    for k, u in units.items():
        t = tutos(u)
        d = rep_["by_category"].setdefault(u["cat"] or "(sans catégorie)", [0, 0])
        d[1] += 1
        if t:
            d[0] += 1
            rep_["covered"].append((u["name"], u["cat"]))
            if u["status"].upper() != "OK":
                rep_["covered_not_ok"].append((u["name"], u["status"], t))
            if len(t) > 1:
                rep_["multi"].append((u["name"], t))
            f = u["file"].lower()
            if "oui" in f or "modif" in f:
                for tt in t:
                    rep_["to_rerun"].setdefault(tt, []).append(u["name"])
        else:
            rep_["uncovered"].append((u["name"], u["cat"]))
    rep_["to_rerun"] = sorted(rep_["to_rerun"].items())

    if coverage:
        present = {k for k in units if not k.startswith("#row")}
        for d in coverage.get("declared", []):
            if d["key"] and d["key"].lower() not in present:
                rep_["orphans"].append((d["label"], d["raw"]))
        rep_["invalid"] = list(coverage.get("invalid", []))
        rep_["without"] = list(coverage.get("without", []))
        rep_["sources"] = list(coverage.get("sources", []))
    return rep_


def coverage_detail_rows(headers, rows, coverage):
    """Table détaillée (une ligne par identifiant déclaré) pour la feuille
    'Couverture' : (headers, rows)."""
    lab = COLUMN_LABELS
    h = ["Workflow", "Source", "Identifiant déclaré", "Trouvé ?",
         "Widget", "Catégorie", "Statut widget"]
    found = {}
    if lab["widget_key"] in headers:
        ik = headers.index(lab["widget_key"])
        inm = headers.index(lab["name"]) if lab["name"] in headers else None
        ica = headers.index(lab["category"]) if lab["category"] in headers else None
        ist = headers.index(lab["statut"]) if lab["statut"] in headers else None
        iva = headers.index(lab["variant"]) if lab["variant"] in headers else None
        for r in rows:
            if iva is not None and str(r[iva] or "") == "dev":
                continue
            k = str(r[ik] or "").lower()
            if not k:
                continue
            g = lambda i: "" if i is None else str(r[i] or "")
            prev = found.get(k)
            if prev is None or (prev[2].upper() != "OK" and g(ist).upper() == "OK"):
                found[k] = (g(inm), g(ica), g(ist))
    out = []
    for d in (coverage or {}).get("declared", []):
        if not d["key"]:
            out.append([d["label"], d["source"], d["raw"], "identifiant invalide", "", "", ""])
            continue
        w = found.get(d["key"].lower())
        if w:
            out.append([d["label"], d["source"], d["raw"], "oui", w[0], w[1], w[2]])
        else:
            out.append([d["label"], d["source"], d["raw"], "non (orphelin)", "", "", ""])
    for label in (coverage or {}).get("without", []):
        out.append([label, "", f"(aucun {TESTED_FIELD})", "", "", "", ""])
    return h, out


def _coverage_summary_lines(rep_):
    """Section(s) de récapitulatif à partir de coverage_report()."""
    out = []
    tot, n_cov = rep_["total"], len(rep_["covered"])
    out.append(("COUVERTURE PAR LES WORKFLOWS", None))
    if rep_["sources"]:
        out.append(("Sources lues", ", ".join(rep_["sources"])))
    out.append(("Widgets (prod) couverts", f"{n_cov} / {tot}  ({_pct(n_cov, tot)})"))
    out.append(("Widgets non couverts", len(rep_["uncovered"])))
    out.append(("Couverts par plusieurs workflows", len(rep_["multi"])))
    out.append(("Couverts mais statut ≠ OK", len(rep_["covered_not_ok"])))
    for nm, st, t in rep_["covered_not_ok"]:
        out.append((f"  • {nm}", f"{st}  [{', '.join(t)}]"))
    out.append(("Workflows sans tested_widgets", len(rep_["without"])))
    for t in rep_["without"]:
        out.append((f"  • {t}", ""))
    note = " (diagnostic filtré par catégorie)" if rep_["filtered"] else ""
    out.append((f"Identifiants orphelins{note}", len(rep_["orphans"])))
    for t, raw in rep_["orphans"]:
        out.append((f"  • {t}", raw))
    if rep_["invalid"]:
        out.append(("Identifiants invalides", len(rep_["invalid"])))
        for t, raw in rep_["invalid"]:
            out.append((f"  • {t}", raw))
    out.append(("WORKFLOWS À RELANCER (widget .py modifié)", None))
    if not rep_["compare"]:
        out.append(("Workflows à relancer", RERUN_UNAVAILABLE))
    else:
        out.append(("Workflows à relancer", len(rep_["to_rerun"])))
        for t, ws in rep_["to_rerun"]:
            out.append((f"  • {t}", ", ".join(ws)))
    if rep_["by_category"]:
        out.append(("COUVERTURE PAR CATÉGORIE (couverts / total)", None))
        for cat in sorted(rep_["by_category"]):
            c, t = rep_["by_category"][cat]
            out.append((cat, f"{c} / {t}  ({_pct(c, t)})"))
    return out


def _file_is_modified(value):
    """True si une cellule « Modifié vs réf. » indique une modification."""
    v = str(value or "").lower()
    return "oui" in v or "modif" in v


def modified_prod_widgets(headers, rows):
    """{clé_minuscule: nom_widget} des widgets PROD dont le .py est modifié
    par rapport à la référence. None si le diagnostic ne permet pas de le
    savoir (pas de comparaison à la référence ou pas de colonne identifiant)."""
    lab = COLUMN_LABELS
    if lab["file_status"] not in headers or lab["widget_key"] not in headers:
        return None
    i_f, i_k = headers.index(lab["file_status"]), headers.index(lab["widget_key"])
    i_n = headers.index(lab["name"]) if lab["name"] in headers else None
    i_v = headers.index(lab["variant"]) if lab["variant"] in headers else None
    out = {}
    for r in rows:
        if i_v is not None and str(r[i_v] or "") == "dev":
            continue
        f = str(r[i_f] or "").lower()
        k = str(r[i_k] or "").lower()
        if k and ("oui" in f or "modif" in f):
            out[k] = "" if i_n is None else str(r[i_n] or "")
    return out


def rerun_for_entry(entry, modified):
    """Noms des widgets modifiés (prod) déclarés par une entrée de batch."""
    if not modified:
        return []
    out = []
    for raw in declared_widgets(entry):
        k = widget_key(raw)
        if k and k.lower() in modified:
            nm = modified[k.lower()] or k
            if nm not in out:
                out.append(nm)
    return out


def coverage_short_text(rep_):
    """Résumé d'une ligne pour l'UI."""
    if not rep_:
        return ""
    tot, n = rep_["total"], len(rep_["covered"])
    parts = [f"Couverture : {n}/{tot} widgets prod couverts ({_pct(n, tot)})"]
    if rep_["covered_not_ok"]:
        parts.append(f"{len(rep_['covered_not_ok'])} couvert(s) en erreur")
    if rep_["orphans"]:
        parts.append(f"{len(rep_['orphans'])} orphelin(s)")
    if rep_["without"]:
        parts.append(f"{len(rep_['without'])} workflow(s) sans {TESTED_FIELD}")
    if not rep_["compare"]:
        parts.append("workflows à relancer : comparaison à la référence inactive")
    elif rep_["to_rerun"]:
        parts.append(f"{len(rep_['to_rerun'])} workflow(s) à relancer")
    return " — ".join(parts)


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


# ── Récapitulatif (statistiques) ────────────────────────────────────────────

def _pct(n, total):
    return f"{(100.0 * n / total):.0f} %" if total else "—"


def build_summary(headers, rows, coverage=None, filtered=False):
    """Statistiques récapitulatives calculées à partir des en-têtes + lignes.

    Robuste : chaque section n'est produite que si sa colonne est présente.
    Renvoie une liste (label, valeur) ; une valeur None marque un titre de
    section (rendu en gras dans le .xlsx).
    """
    def col(key, *aliases):
        """Index de colonne d'après la clé interne (COLUMN_LABELS) + alias.

        Les alias couvrent les exports au schéma différent (workflows :
        'Résultat' pour le statut, 'Tutoriel' ou 'Nom' pour le nom)."""
        for nm in (COLUMN_LABELS.get(key, key), *aliases):
            if nm in headers:
                return headers.index(nm)
        return None

    c_status = col("statut", "Résultat")
    c_name = col("name", "Tutoriel", "Nom")
    c_cat = col("category")
    c_file = col("file_status")
    c_pver = col("pkg_status")
    c_pkg = col("package")
    c_var = col("variant")
    c_launch = col("launch")

    def cell(row, ci):
        return "" if ci is None or ci >= len(row) else str(row[ci]).strip()

    # ── Unités "widget" : on dédoublonne les lignes (widget, librairie) ──
    # Clé = (nom, catégorie, version, fichier .py) si dispo, sinon l'index de
    # ligne. Le fichier distingue deux widgets homonymes de la même catégorie
    # (prod/dev, ou deux add-ons différents) : sans lui, ils étaient fusionnés
    # et seul le statut .py de la première ligne était compté.
    units = {}  # clé -> {"status":..., "file":...}
    for i, row in enumerate(rows):
        if c_name is not None:
            key = (cell(row, c_name), cell(row, c_cat), cell(row, c_var),
                   cell(row, c_launch))
        else:
            key = i
        u = units.setdefault(key, {"status": "", "file": ""})
        if not u["status"]:
            u["status"] = cell(row, c_status)
        if not u["file"]:
            u["file"] = cell(row, c_file)

    total_units = len(units)
    out = [("RÉCAPITULATIF", None)]
    out.append(("Lignes (page brute)", len(rows)))
    out.append(("Widgets analysés", total_units))
    if c_var is not None and c_name is not None:
        n_dev = sum(1 for k in units if k[2] == "dev")
        out.append(("  dont versions prod", total_units - n_dev))
        out.append(("  dont versions dev", n_dev))

    # ── Statuts OK / NOK ──
    if c_status is not None:
        n_ok = sum(1 for u in units.values() if u["status"].upper() == "OK")
        n_nok = sum(1 for u in units.values() if u["status"].upper() == "NOK")
        n_err = sum(1 for u in units.values() if u["status"].upper().startswith("ERR"))
        n_other = total_units - n_ok - n_nok - n_err
        out.append(("STATUTS", None))
        out.append(("OK", f"{n_ok}  ({_pct(n_ok, total_units)})"))
        out.append(("NOK", f"{n_nok}  ({_pct(n_nok, total_units)})"))
        out.append(("Erreur", f"{n_err}  ({_pct(n_err, total_units)})"))
        if n_other:
            out.append(("Autres / non lancés", n_other))

    # ── Fichiers .py modifiés (si comparaison) ──
    if c_file is not None:
        vals = [u["file"] for u in units.values() if u["file"]]
        def _n(pred):
            return sum(1 for v in vals if pred(v.lower()))
        n_mod = _n(lambda v: "oui" in v or "modif" in v)
        n_unch = _n(lambda v: v == "non")
        n_new = _n(lambda v: "nouveau" in v)
        n_pb = _n(lambda v: "introuvable" in v or "illisible" in v)
        out.append((".PY vs RÉFÉRENCE", None))
        out.append(("Modifiés", n_mod))
        out.append(("Inchangés", n_unch))
        out.append(("Nouveaux (absents réf)", n_new))
        if n_pb:
            out.append(("Illisibles / introuvables", n_pb))

    elif COLUMN_LABELS["name"] in headers:        # diagnostic sans comparaison
        out.append((".PY vs RÉFÉRENCE", None))
        out.append(("Modifiés / inchangés / nouveaux", RERUN_UNAVAILABLE))

    # ── Différences pip (si comparaison + grain fin) ──
    if c_pver is not None:
        changed = []       # (package, "ref → actuelle")
        n_same = n_new = n_absent = n_offpip = 0
        for row in rows:
            s = cell(row, c_pver)
            if not s:
                continue
            low = s.lower()
            if s.startswith("= "):
                n_same += 1
            elif "→" in s:
                changed.append((cell(row, c_pkg), s))
            elif low.startswith("nouvelle"):
                n_new += 1
            elif low.startswith("absente"):
                n_absent += 1
            elif low.startswith("(hors pip"):
                n_offpip += 1
        out.append(("LIBRAIRIES PIP vs RÉFÉRENCE", None))
        out.append(("Versions changées", len(changed)))
        out.append(("Versions identiques", n_same))
        out.append(("Nouvelles (absentes réf)", n_new))
        out.append(("Absentes (présentes en réf)", n_absent))
        if n_offpip:
            out.append(("Hors pip / local", n_offpip))
        for pkg, s in changed:
            out.append((f"  • {pkg}", s))

    # ── Répartition par catégorie ──
    if c_cat is not None and c_name is not None:
        cats = {}
        for (nm, cat, _var, _f), u in units.items():
            d = cats.setdefault(cat or "(sans catégorie)", [0, 0])
            d[0] += 1
            if u["status"].upper() == "OK":
                d[1] += 1
        if cats:
            out.append(("PAR CATÉGORIE (OK / total)", None))
            for cat in sorted(cats):
                tot, ok = cats[cat][0], cats[cat][1]
                out.append((cat, f"{ok} / {tot}"))

    # ── Couverture par les tutoriels (si colonnes présentes) ──
    try:
        cov_rep = coverage_report(headers, rows, coverage, filtered)
    except Exception:
        cov_rep = None
    if cov_rep:
        out += _coverage_summary_lines(cov_rep)

    return out


# ── Écriture des résultats ──────────────────────────────────────────────────

def _write_delimited(path, headers, rows, delimiter):
    path = Path(path)
    # utf-8-sig => ouverture propre dans Excel (accents)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=delimiter)
        w.writerow(headers)
        w.writerows(rows)
    return path


def _write_xlsx(path, headers, rows, metadata=None, coverage=None, filtered=False):
    try:
        from openpyxl import Workbook
    except Exception as e:
        raise RuntimeError(
            "Le format .xlsx nécessite le paquet 'openpyxl'. "
            "Installez-le (pip install openpyxl) ou choisissez un fichier .csv."
        ) from e
    from openpyxl.styles import Font

    path = Path(path)
    wb = Workbook()
    ws = wb.active
    # Résultats de workflows (colonne « Résultat ») ou diagnostic des widgets.
    ws.title = "Résultats" if "Résultat" in headers else "Diagnostic"
    ws.append(list(headers))
    for r in rows:
        ws.append(list(r))

    # Feuille récap, placée en première position (page d'accueil du classeur).
    try:
        summary = build_summary(list(headers), rows, coverage, filtered)
    except Exception:
        summary = None
    if summary:
        rs = wb.create_sheet("Récapitulatif")
        for label, value in summary:
            if value is None:                       # titre de section
                cell = rs.cell(row=rs.max_row + 1, column=1, value=str(label))
                cell.font = Font(bold=True)
            else:
                rs.append([str(label), "" if value is None else str(value)])
        rs.column_dimensions["A"].width = 34
        rs.column_dimensions["B"].width = 24
        wb.move_sheet("Récapitulatif", -(wb.index(rs)))  # -> index 0

    if coverage and COLUMN_LABELS["widget_key"] in headers:
        try:
            ch, crows = coverage_detail_rows(list(headers), rows, coverage)
            cs = wb.create_sheet("Couverture")
            cs.append(ch)
            for c in cs[1]:
                c.font = Font(bold=True)
            for r in crows:
                cs.append(r)
            for col, w in zip("ABCDEFG", (32, 18, 58, 16, 30, 28, 20)):
                cs.column_dimensions[col].width = w
        except Exception:
            pass

    if metadata:
        ms = wb.create_sheet("Métadonnées")
        ms.append(["Clé", "Valeur"])
        for k, v in metadata:
            ms.append([k, "" if v is None else str(v)])

    wb.save(path)
    return path


def write_rows(path, headers, rows, metadata=None, coverage=None, filtered=False):
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
        return _write_xlsx(p, headers, rows, metadata, coverage, filtered)

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
    # Détail de couverture dans un sidecar dédié.
    if coverage and COLUMN_LABELS["widget_key"] in headers:
        try:
            ch, crows = coverage_detail_rows(list(headers), rows, coverage)
            side = p.with_suffix(p.suffix + ".coverage.csv")
            with open(side, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(ch)
                w.writerows(crows)
        except Exception:
            pass
    # Récapitulatif dans un sidecar dédié.
    try:
        summary = build_summary(list(headers), rows, coverage, filtered)
    except Exception:
        summary = None
    if summary:
        side = p.with_suffix(p.suffix + ".summary.csv")
        with open(side, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            for label, value in summary:
                w.writerow([label, "" if value is None else value])
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
