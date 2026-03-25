# secrets_manager.py
import keyring
import json
from typing import Any, Dict, Optional, Tuple

class SecretManager:
    """
    Gestionnaire de secrets basé sur 'keyring', sans notion de préfixe.
    Un 'service' = un ensemble logique de paires clé/valeur.
    La classe maintient :
      - un index des clés par service (clé spéciale '__keys_index__' dans le service),
      - un registre global des services (service '__keyring_registry__', username '__services_index__').
    """

    # Registre global
    _REGISTRY_SERVICE = "__ODM_keyring_registry__"
    _REGISTRY_USERNAME = "__ODM_services_index__"  # JSON: ["serviceA", "serviceB", ...]

    def __init__(self, service: str):
        """
        Crée un gestionnaire associé à un service donné.
        """
        if not isinstance(service, str) or not service:
            raise ValueError("service must be a non-empty string.")
        self.service = service

    # ------------------------
    # Utilitaires (statique)
    # ------------------------
    @staticmethod
    def _encode_value(value: Any) -> str:
        if isinstance(value, str):
            return value
        return "__json__:" + json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _decode_value(stored: Optional[str]) -> Any:
        if stored is None:
            return None
        if stored.startswith("__json__:"):
            return json.loads(stored[len("__json__:"):])
        return stored

    @staticmethod
    def _flatten_dict(d: Dict[str, Any], parent: str = "", sep: str = ".") -> Dict[str, Any]:
        flat: Dict[str, Any] = {}
        for k, v in d.items():
            key = f"{parent}{sep}{k}" if parent else k
            if isinstance(v, dict):
                flat.update(SecretManager._flatten_dict(v, key, sep=sep))
            else:
                flat[key] = v
        return flat

    @staticmethod
    def _unflatten_dict(flat: Dict[str, Any], sep: str = ".") -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for compound, v in flat.items():
            parts = compound.split(sep)
            node = out
            for p in parts[:-1]:
                node = node.setdefault(p, {})
            node[parts[-1]] = v
        return out

    # ------------------------
    # Index de service
    # ------------------------
    def _get_index(self) -> set[str]:
        raw = keyring.get_password(self.service, "__ODM_keys_index__")
        if not raw:
            return set()
        try:
            return set(json.loads(raw))
        except Exception:
            return set()

    def _save_index(self, keys: set[str]) -> None:
        keyring.set_password(self.service, "__ODM_keys_index__", json.dumps(sorted(keys)))

    # ------------------------
    # Registre global
    # ------------------------
    @classmethod
    def _get_services_index(cls) -> set[str]:
        raw = keyring.get_password(cls._REGISTRY_SERVICE, cls._REGISTRY_USERNAME)
        if not raw:
            return set()
        try:
            return set(json.loads(raw))
        except Exception:
            return set()

    @classmethod
    def _save_services_index(cls, services: set[str]) -> None:
        keyring.set_password(cls._REGISTRY_SERVICE, cls._REGISTRY_USERNAME, json.dumps(sorted(services)))

    def _register_service(self) -> None:
        services = self._get_services_index()
        if self.service not in services:
            services.add(self.service)
            self._save_services_index(services)

    def _maybe_unregister_service_if_empty(self) -> None:
        if self._get_index():
            return
        services = self._get_services_index()
        if self.service in services:
            services.remove(self.service)
            self._save_services_index(services)

    # ------------------------
    # API publique d'instance
    # ------------------------
    def store(
        self,
        secrets: Dict[str, Any],
        *,
        overwrite: bool = False,
        nested: bool = False,
    ) -> Tuple[int, Dict[str, str]]:
        """
        Stocke un dictionnaire de secrets dans ce service.
        - str stocké tel quel ; autres types sérialisés JSON avec préfixe '__json__:'.
        - nested=True permet de donner un dict imbriqué (notation 'a.b.c' interne).
        - overwrite=False n'écrase pas une clé existante.

        Retour: (nb_stored, details: dict key -> 'stored'|'skipped')
        """
        flat = self._flatten_dict(secrets) if nested else dict(secrets)
        results: Dict[str, str] = {}
        stored_count = 0
        index = self._get_index()

        for k, v in flat.items():
            existing = keyring.get_password(self.service, k)
            if existing is not None and not overwrite:
                results[k] = "skipped"
                continue
            keyring.set_password(self.service, k, self._encode_value(v))
            index.add(k)
            results[k] = "stored"
            stored_count += 1

        self._save_index(index)
        if stored_count:
            self._register_service()
        return stored_count, results

    def load(
        self,
        keys_or_schema: Any,
        *,
        nested: bool = False,
        raise_if_missing: bool = False,
    ) -> Dict[str, Any]:
        """
        Charge un dictionnaire *entièrement déchiffré* pour le service.
        - keys_or_schema: liste/tuple/set de clés OU dict (plat ou imbriqué si nested=True).
          Si dict fourni, seules les clés servent, les valeurs sont ignorées.
        - nested=True reconstruit la structure imbriquée si dict fourni.
        - raise_if_missing=True lève KeyError si au moins une clé est absente.
        """
        if isinstance(keys_or_schema, dict):
            keys_iter = (self._flatten_dict(keys_or_schema) if nested else keys_or_schema).keys()
        elif isinstance(keys_or_schema, (list, tuple, set)):
            keys_iter = [str(k) for k in keys_or_schema]
        else:
            raise TypeError("keys_or_schema must be a dict or a list/tuple/set of keys.")

        flat_result: Dict[str, Any] = {}
        missing: list[str] = []

        for k in keys_iter:
            stored = keyring.get_password(self.service, k)
            if stored is None:
                flat_result[k] = None
                missing.append(k)
            else:
                flat_result[k] = self._decode_value(stored)

        if missing and raise_if_missing:
            raise KeyError(f"Missing secrets in keyring for keys: {missing}")

        if isinstance(keys_or_schema, dict):
            return self._unflatten_dict(flat_result) if nested else flat_result
        return flat_result

    def delete(self, key: str, *, silent: bool = False) -> bool:
        """
        Supprime une clé de ce service. Met à jour l'index et le registre si service vide.
        Retourne True si supprimée, False si absente (si silent=True).
        """
        existing = keyring.get_password(self.service, key)
        if existing is None:
            if silent:
                return False
            raise KeyError(f"No secret found for key '{key}' in service '{self.service}'")

        keyring.delete_password(self.service, key)
        index = self._get_index()
        index.discard(key)
        self._save_index(index)
        self._maybe_unregister_service_if_empty()
        return True

    def list_keys(self) -> list[str]:
        """
        Liste toutes les clés connues pour ce service.
        """
        return sorted(self._get_index())

    def clear(self, *, silent: bool = True) -> int:
        """
        Supprime *toutes* les clés de ce service, efface l'index local,
        et retire le service du registre global.
        Retourne le nombre de clés supprimées (hors entrée d'index).
        """
        keys = self._get_index()
        deleted = 0

        for k in list(keys):
            try:
                keyring.delete_password(self.service, k)
                deleted += 1
            except Exception:
                if not silent:
                    raise

        # supprimer l'index
        try:
            keyring.delete_password(self.service, "__ODM_keys_index__")
        except Exception:
            if not silent:
                raise

        self._maybe_unregister_service_if_empty()
        return deleted


    def load_all(self) -> dict:
        """
        Charge toutes les clés présentes pour ce service et renvoie un dict imbriqué.
        """
        keys = self.list_keys()
        flat = {}
        for k in keys:
            stored = keyring.get_password(self.service, k)
            flat[k] = self._decode_value(stored)
        return self._unflatten_dict(flat, sep=".")
    # ------------------------
    # API de classe (global)
    # ------------------------
    @classmethod
    def list_services(cls) -> list[str]:
        """
        Liste tous les services connus (enregistrés via cette classe).
        """
        return sorted(cls._get_services_index())


# pip install keyring
# # Lister tous les services connus par le module
#print("->",SecretManager.list_services())


# # Initialiser un gestionnaire pour un service
# sm = SecretManager("service_prod")
#
# # Stocker (plat)
#sm.store({"db.user": "admin", "db.password": "xyz"}, overwrite=True)
#
# # Stocker (imbriqué)
# sm.store({"api": {"key": "ABC123", "timeout": 60}}, nested=True, overwrite=True)
#
# charger betement tout
# print(sm.load_all())


# # Purger totalement le service
# deleted = sm.clear()
# print("Supprimées:", deleted)


# autre fonction utile
# # Lister les clés
#print(sm.list_keys())  # -> ['api.key', 'api.timeout', 'db.password', 'db.user']
#
# # Charger via schéma imbriqué
# schema = {"db": {"user": None, "password": None}, "api": {"key": None, "timeout": None}}
#schema = {}
#print(sm.load(schema, nested=True, raise_if_missing=True))
# # -> {'db': {'user': 'admin', 'password': 'xyz'}, 'api': {'key': 'ABC123', 'timeout': 60}}
#
# # Supprimer une clé
# sm.delete("db.password")
#

#

