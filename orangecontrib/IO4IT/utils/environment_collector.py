import sys
import platform
import datetime

try:
    import importlib.metadata as importlib_metadata
except ImportError:
    import importlib_metadata  # fallback for Python < 3.8


class EnvironmentCollector:
    """
    Utilitaire pour collecter les informations d'environnement système
    (OS, Python, dépendances pip) sans recourir à subprocess.
    """

    @staticmethod
    def _dependencies_freeze_space() -> str:
        """
        Retourne l'équivalent d'un `pip freeze` (Package==Version ...)
        séparé par des retours à la ligne.
        Utilise importlib.metadata (pas de subprocess).
        """
        try:
            dists = sorted(
                importlib_metadata.distributions(),
                key=lambda d: (d.metadata.get("Name", "") or "").lower()
            )
            parts = []
            for dist in dists:
                name = (dist.metadata.get("Name") or "").strip()
                version = getattr(dist, "version", None)
                if name and version:
                    parts.append(f"{name}=={version}")
            return "\n\r".join(parts)
        except Exception as e:
            return f"Error collecting dependencies: {e}"

    def _collect(self):
        """
        Collecte les informations clés de l'environnement courant.

        Returns:
            tuple: (keys: list[str], vals: list[str|None])
                   - keys  : noms des colonnes
                   - vals  : valeurs correspondantes
                             (None pour "Row number", géré en aval avec np.arange)
        """
        keys = [
            "Row number",
            "Current Time",
            "OS",
            "Machine",
            "Processor",
            "Python Version",
            "Python Executable",
            "Dependencies",
        ]

        vals = [
            None,  # Row number (géré dans _apply avec np.arange)
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            platform.platform(),
            platform.machine(),
            platform.processor() or platform.machine(),
            sys.version.replace("\n", " "),
            sys.executable,
            self._dependencies_freeze_space(),
        ]

        return keys, vals