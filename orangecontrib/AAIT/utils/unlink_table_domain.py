from Orange.data import Table, Domain, Instance, DiscreteVariable, ContinuousVariable, StringVariable,TimeVariable
import numpy as np

def unlink_domain(table: Table) -> Table:
    dom = table.domain

    # Recrée les variables sans compute_value
    new_attrs  = [v.copy(compute_value=None) for v in dom.attributes]
    new_cls    = [v.copy(compute_value=None) for v in dom.class_vars]
    new_metas  = [v.copy(compute_value=None) for v in dom.metas]
    new_domain = Domain(new_attrs, new_cls, new_metas)

    instances = []
    for row in table:
        # on évalue toutes les valeurs ici (les compute_value sont calculés)
        attr_vals = [row[v] for v in dom.attributes]
        cls_vals  = [row[v] for v in dom.class_vars]
        inst = Instance(new_domain, attr_vals + cls_vals)

        # on renseigne les métas via l’indexation
        for old_m, new_m in zip(dom.metas, new_metas):
            inst[new_m] = row[old_m]

        instances.append(inst)

    return Table.from_list(new_domain, instances)


#------------------------------------------------------------------
def _var_key(v):
    # Identifie une colonne "logique" : type + nom
    return (type(v), v.name)

def build_union_domain(tables: list[Table]) -> Domain:
    """
    Construit un domaine cible :
    - une variable finale unique par nom
    - ordre/rôle prioritaire dictés par la 1ère apparition globale
    - ordre de la 1ère table préservé
    - colonnes nouvelles des tables suivantes ajoutées à la fin
    - union des modalités pour les DiscreteVariable
    """
    if not tables:
        raise ValueError("tables is empty")

    first_dom = tables[0].domain

    ordered_names = []
    seen_by_name = {}

    def register(v, role):
        name = v.name

        if name not in seen_by_name:
            seen_by_name[name] = {
                "proto": v,
                "role": role,
                "values": []
            }
            ordered_names.append(name)
        else:
            # si la 1ère apparition n'était pas discrète mais qu'une autre l'est,
            # on garde le proto d'origine; seule l'union de catégories sert
            pass

        if isinstance(v, DiscreteVariable):
            for val in v.values:
                if val not in seen_by_name[name]["values"]:
                    seen_by_name[name]["values"].append(val)

    # 1) ordre/rôle prioritaire dictés par la 1ère table
    for v in first_dom.attributes:
        register(v, "attr")
    for v in first_dom.class_vars:
        register(v, "class")
    for v in first_dom.metas:
        register(v, "meta")

    # 2) ajout des variables nouvelles des autres tables
    for t in tables[1:]:
        for v in t.domain.attributes:
            register(v, "attr")
        for v in t.domain.class_vars:
            register(v, "class")
        for v in t.domain.metas:
            register(v, "meta")

    def make_var(proto, values_list):
        if isinstance(proto, DiscreteVariable):
            return DiscreteVariable(proto.name, values=values_list)
        if isinstance(proto, ContinuousVariable):
            return ContinuousVariable(proto.name)
        if isinstance(proto, StringVariable):
            return StringVariable(proto.name)
        if isinstance(proto, TimeVariable):
            return TimeVariable(proto.name)
        return proto.copy(compute_value=None)

    attrs = []
    class_vars = []
    metas = []

    for name in ordered_names:
        info = seen_by_name[name]
        new_var = make_var(info["proto"], info["values"])

        if info["role"] == "attr":
            attrs.append(new_var)
        elif info["role"] == "class":
            class_vars.append(new_var)
        else:
            metas.append(new_var)

    return Domain(attrs, class_vars, metas)

def remap_table_to_domain(table: Table, target_domain: Domain) -> Table:
    """
    Remappe une table vers target_domain, en particulier :
    - Discrete: remap code -> label -> code cible (union)
    - Continuous: copie float
    - String/meta: stocke objets/texte
    Colonnes absentes: NaN / None
    """
    n = len(table)

    # blocs (X, Y, M) compatibles Orange
    X = np.full((n, len(target_domain.attributes)), np.nan, dtype=float) if target_domain.attributes else np.empty((n, 0), dtype=float)
    Y = np.full((n, len(target_domain.class_vars)), np.nan, dtype=float) if target_domain.class_vars else np.empty((n, 0), dtype=float)
    M = np.empty((n, len(target_domain.metas)), dtype=object) if target_domain.metas else np.empty((n, 0), dtype=object)

    # map nom -> variable source (vars + metas)
    src_dom = table.domain
    src_by_name = {v.name: v for v in list(src_dom.variables) + list(src_dom.metas)}

    def _safe_raw_value(val):
        if hasattr(val, "value"):
            return val.value
        return val

    def _safe_str_label(val):
        raw = _safe_raw_value(val)
        if raw is None:
            return None
        s = str(raw)
        if s == "?":
            return None
        return s

    def fill_block(target_vars, block, is_meta: bool):
        for j, tv in enumerate(target_vars):
            sv = src_by_name.get(tv.name)
            if sv is None:
                continue

            col = table.get_column(sv)

            # ------------------------------------------------------------------
            # 1) cible discrète : on doit toujours produire des CODES Orange valides
            # ------------------------------------------------------------------
            if isinstance(tv, DiscreteVariable):
                out = np.full(n, np.nan, dtype=float)
                tgt_index = {label: idx for idx, label in enumerate(tv.values)}

                # source discrète -> code source -> label source -> code cible
                if isinstance(sv, DiscreteVariable):
                    for i in range(n):
                        c = col[i]
                        if np.isnan(c):
                            continue
                        ic = int(c)
                        if 0 <= ic < len(sv.values):
                            label = sv.values[ic]
                            out[i] = tgt_index.get(label, np.nan)

                # source non discrète -> valeur brute -> str(...) -> code cible
                else:
                    for i in range(n):
                        val = table[i, sv]
                        label = _safe_str_label(val)
                        if label is None:
                            continue
                        out[i] = tgt_index.get(label, np.nan)

                block[:, j] = out

            # ------------------------------------------------------------------
            # 2) cible continue
            # ------------------------------------------------------------------
            elif isinstance(tv, ContinuousVariable) and not is_meta:
                out = np.full(n, np.nan, dtype=float)

                if isinstance(sv, DiscreteVariable):
                    for i in range(n):
                        c = col[i]
                        if np.isnan(c):
                            continue
                        ic = int(c)
                        if 0 <= ic < len(sv.values):
                            try:
                                out[i] = float(sv.values[ic])
                            except Exception:
                                out[i] = np.nan
                else:
                    for i in range(n):
                        val = table[i, sv]
                        raw = _safe_raw_value(val)
                        try:
                            out[i] = float(raw)
                        except Exception:
                            out[i] = np.nan

                block[:, j] = out

            # ------------------------------------------------------------------
            # 3) cible meta / string
            # ------------------------------------------------------------------
            elif is_meta or isinstance(tv, StringVariable):
                out = np.empty(n, dtype=object)
                for i in range(n):
                    if isinstance(sv, DiscreteVariable):
                        c = col[i]
                        if np.isnan(c):
                            out[i] = None
                        else:
                            ic = int(c)
                            if 0 <= ic < len(sv.values):
                                out[i] = sv.values[ic]
                            else:
                                out[i] = None
                    else:
                        val = table[i, sv]
                        raw = _safe_raw_value(val)
                        out[i] = raw
                block[:, j] = out

            # ------------------------------------------------------------------
            # 4) fallback : conversion float prudente
            # ------------------------------------------------------------------
            else:
                out = np.full(n, np.nan, dtype=float)

                if isinstance(sv, DiscreteVariable):
                    for i in range(n):
                        c = col[i]
                        if np.isnan(c):
                            continue
                        ic = int(c)
                        if 0 <= ic < len(sv.values):
                            try:
                                out[i] = float(sv.values[ic])
                            except Exception:
                                out[i] = np.nan
                else:
                    for i in range(n):
                        val = table[i, sv]
                        raw = _safe_raw_value(val)
                        try:
                            out[i] = float(raw)
                        except Exception:
                            out[i] = np.nan

                block[:, j] = out

    fill_block(target_domain.attributes, X, is_meta=False)
    fill_block(target_domain.class_vars, Y, is_meta=False)
    fill_block(target_domain.metas, M, is_meta=True)

    return Table.from_numpy(
        target_domain,
        X,
        Y if Y.size else None,
        M if M.size else None
    )

def concatenate_tables_harmonized(tables: list[Table]) -> Table:
    """
    Concatène des tables en harmonisant les DiscreteVariable (union + remap).
    """

    if not tables:
        raise ValueError("tables is empty")
    if len(tables) == 1:
        return tables[0]

    target = build_union_domain(tables)
    mapped = [remap_table_to_domain(t, target) for t in tables]
    return Table.concatenate(mapped)



