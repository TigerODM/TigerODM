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
import sys
import ast
import csv
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


def file_dates(py_file):
    stats = py_file.stat()
    return (datetime.fromtimestamp(stats.st_ctime).strftime('%Y-%m-%d %H:%M:%S'),
            datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S'))


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

def _columns_for(include_packages, include_dates):
    """Retourne la liste ordonnée (en-tête, clé_interne) des colonnes."""
    cols = [
        ("Widget_Orange_Name", "name"),
        ("Widget", "widget"),
        ("Catégorie", "category"),
    ]
    if include_packages:
        cols.append(("Package pip", "package"))
    cols.append(("Statut", "statut"))
    if include_dates:
        cols.append(("Date Création", "date_creation"))
        cols.append(("Date Modification", "date_modification"))
    cols.append(("Lancer le widget", "launch"))
    return cols


def launch_command(file_path):
    """Commande à coller dans un cmd pour lancer le widget :
    "<python.exe>" "<chemin_du_widget.py>"."""
    if not file_path:
        return ""
    return f'"{sys.executable}" "{file_path}"'


def _make_record(name, widget_label, category, statut, file_path,
                 package="", include_dates=True):
    """Construit un enregistrement complet (dict) pour un widget."""
    if file_path is not None:
        widget = file_path.name
        launch = launch_command(file_path)
        if include_dates:
            dt_c, dt_m = file_dates(file_path)
        else:
            dt_c, dt_m = "", ""
    else:
        widget = widget_label if widget_label is not None else ""
        launch = ""
        dt_c, dt_m = "", ""
    return {
        "name": name,
        "widget": widget,
        "category": category,
        "package": package,
        "statut": statut,
        "date_creation": dt_c,
        "date_modification": dt_m,
        "launch": launch,
    }


def _project(records, cols):
    """Projette les enregistrements (dicts) sur les colonnes choisies."""
    return [[rec.get(key, "") for _, key in cols] for rec in records]


# ── Scan principal (paramétrable) ───────────────────────────────────────────

def run_diagnostic(selected_categories=None, include_packages=True,
                   include_dates=True, progress_callback=None, should_cancel=None):
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
    include_dates : bool
        Si False, n'ajoute pas les colonnes "Date Création" / "Date Modification".
    progress_callback : callable(done, total, message) | None
        Appelé régulièrement pour suivre l'avancement.
    should_cancel : callable() -> bool | None
        Si renvoie True, le scan s'arrête proprement et retourne le partiel.

    Retourne
    --------
    (headers, rows)
        La colonne "Lancer le widget" contient la commande
        "<python.exe>" "<chemin_du_widget.py>" à coller dans un cmd.
    """
    registry = get_registry()

    selected = {c.strip().lower() for c in (selected_categories or [])}

    def category_selected(cat):
        return not selected or (cat or "").strip().lower() in selected

    def cancelled():
        return bool(should_cancel) and should_cancel()

    cols = _columns_for(include_packages, include_dates)
    headers = [h for h, _ in cols]
    records = []
    loaded_modules = set()

    # Phase 1 : widgets chargés (registry)
    phase1 = sorted(registry.widgets(), key=lambda d: (d.category or "", d.name))

    # Phase 2 : widgets potentiellement cassés / non chargés
    phase2 = []
    for category, pkg_name in widget_packages():
        if not category_selected(category):
            continue
        for modname in iter_widget_modules(pkg_name):
            phase2.append((category, modname))

    total = len(phase1) + len(phase2)
    done = 0

    # --- Phase 1 ---
    for desc in phase1:
        if cancelled():
            return headers, _project(records, cols)
        loaded_modules.add(desc.qualified_name.rsplit(".", 1)[0])
        category = desc.category or "(sans catégorie)"
        done += 1
        if progress_callback:
            progress_callback(done, total, desc.name)
        if not category_selected(category):
            continue

        src = widget_source_file(desc)
        if src is None:
            records.append(_make_record(
                desc.name, "(fichier introuvable)", category, "introuvable",
                None, include_dates=include_dates))
            continue

        if include_packages:
            pkgs = packages_of(src) or ["(aucun)"]
            for pkg in pkgs:
                records.append(_make_record(
                    desc.name, None, category, "OK", src,
                    package=pkg, include_dates=include_dates))
        else:
            records.append(_make_record(
                desc.name, None, category, "OK", src,
                include_dates=include_dates))

    # --- Phase 2 ---
    for category, modname in phase2:
        if cancelled():
            return headers, _project(records, cols)
        done += 1
        if progress_callback:
            progress_callback(done, total, modname)

        if modname in loaded_modules:
            continue  # déjà présent dans le registry -> OK
        f = module_file(modname)  # find_spec n'exécute pas le module
        if f is None:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        widgets_found = ast_widgets(tree)
        if not widgets_found:
            continue  # ce module n'est pas un widget (helper, base abstraite…)

        display = widgets_found[0][1]
        # On tente l'import pour capturer la raison d'un éventuel échec
        try:
            importlib.import_module(modname)
            statut = "non chargé (import OK, absent du registry)"
        except Exception as e:
            statut = f"{type(e).__name__}: {e}"

        if include_packages:
            pkgs = packages_of(f) or ["(aucun)"]
            for pkg in pkgs:
                records.append(_make_record(
                    display, None, category, statut, f,
                    package=pkg, include_dates=include_dates))
        else:
            records.append(_make_record(
                display, None, category, statut, f,
                include_dates=include_dates))

    return headers, _project(records, cols)


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
    """Construit une Orange Table (metas = colonnes texte). Utile pour utilisation via widget python script"""
    import numpy as np
    from Orange.data import Table, Domain, StringVariable

    domain = Domain([], metas=[StringVariable(h) for h in headers])
    metas = np.array(rows, dtype=object) if rows else np.empty((0, len(headers)), dtype=object)
    return Table.from_numpy(domain, np.empty((len(rows), 0)), metas=metas)