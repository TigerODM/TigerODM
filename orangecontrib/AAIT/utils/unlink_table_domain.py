from Orange.data import Table, Domain, Instance, DiscreteVariable, ContinuousVariable, StringVariable
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
    Construit un domaine cible basé sur la 1ère table (ordre et rôles),
    en unifiant les modalités des DiscreteVariable par nom.
    """
    first_dom = tables[0].domain

    # ordre / rôles dictés par la 1ère table
    order_attrs = [(_var_key(v), v) for v in first_dom.attributes]
    order_cls   = [(_var_key(v), v) for v in first_dom.class_vars]
    order_metas = [(_var_key(v), v) for v in first_dom.metas]

    seen = {"attrs": {}, "cls": {}, "metas": {}}

    def add_vars(role: str, vars_):
        for v in vars_:
            k = _var_key(v)
            if k not in seen[role]:
                seen[role][k] = {"proto": v, "values": set()}
            if isinstance(v, DiscreteVariable):
                seen[role][k]["values"].update(v.values)

    for t in tables:
        add_vars("attrs", t.domain.attributes)
        add_vars("cls",   t.domain.class_vars)
        add_vars("metas", t.domain.metas)

    def make_var(proto, values_set):
        # Recrée une variable "déconnectée" (sans compute_value) + union des valeurs si Discrete
        if isinstance(proto, DiscreteVariable):
            values = list(values_set)  # ou sorted(values_set) si tu veux ordre stable alphabétique
            return DiscreteVariable(proto.name, values=values)
        if isinstance(proto, ContinuousVariable):
            return ContinuousVariable(proto.name)
        if isinstance(proto, StringVariable):
            return StringVariable(proto.name)
        # fallback (rare)
        return proto.copy(compute_value=None)

    def build_list(role: str, ordered_keys_and_proto):
        out = []
        for k, proto in ordered_keys_and_proto:
            if k in seen[role]:
                out.append(make_var(seen[role][k]["proto"], seen[role][k]["values"]))
        return out

    new_attrs = build_list("attrs", order_attrs)
    new_cls   = build_list("cls",   order_cls)
    new_metas = build_list("metas", order_metas)
    return Domain(new_attrs, new_cls, new_metas)

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

    def fill_block(target_vars, block, is_meta: bool):
        for j, tv in enumerate(target_vars):
            sv = src_by_name.get(tv.name)
            if sv is None:
                continue

            col = table.get_column(sv)  # ✅ API moderne (remplace get_column_view)

            if isinstance(tv, DiscreteVariable) and isinstance(sv, DiscreteVariable):
                out = np.full(n, np.nan, dtype=float)

                # mapping label -> index cible
                tgt_index = {label: idx for idx, label in enumerate(tv.values)}

                # col est float avec NaN (codes)
                for i in range(n):
                    c = col[i]
                    if np.isnan(c):
                        continue
                    label = sv.values[int(c)]
                    out[i] = tgt_index.get(label, np.nan)

                block[:, j] = out

            elif isinstance(tv, ContinuousVariable) and isinstance(sv, ContinuousVariable) and not is_meta:
                block[:, j] = col.astype(float, copy=False)

            elif is_meta or isinstance(tv, StringVariable):
                # On stocke des objets/texte
                out = np.empty(n, dtype=object)
                for i in range(n):
                    val = table[i, sv]
                    out[i] = val.value if hasattr(val, "value") else str(val)
                block[:, j] = out

            else:
                # fallback : tente float, sinon NaN
                out = np.full(n, np.nan, dtype=float)
                for i in range(n):
                    val = table[i, sv]
                    try:
                        out[i] = float(val)
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
