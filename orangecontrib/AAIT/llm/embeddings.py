import copy

from Orange.data import ContinuousVariable, Domain, Table


def create_embeddings(table, model, column_name, progress_callback=None, argself=None):
    if len(table) == 0:
        return None
    # Copy of input data
    data = copy.deepcopy(table)
    attr_dom = list(data.domain.attributes)
    metas_dom = list(data.domain.metas)
    class_dom = list(data.domain.class_vars)

    # Generate embeddings on column named "content"
    embeddings = None
    rows = []
    for i, row in enumerate(data):
        features = [row[x] for x in attr_dom]
        targets = [row[y] for y in class_dom]
        metas = list(data.metas[i])
        embeddings = model.encode(str(row[column_name]), show_progress_bar=False)
        features += list(embeddings)
        rows.append(features + targets + metas)
        if progress_callback is not None:
            progress_value = float(100 * (i + 1) / len(data))
            progress_callback(progress_value)
        if argself is not None:
            if argself.stop:
                break

    # Generate new Domain to add to data
    n_columns = len(embeddings)
    embeddings_doms = [ContinuousVariable(f"embedding_{i}") for i in range(n_columns)]
    domain = Domain(attributes=attr_dom + embeddings_doms, class_vars=class_dom, metas=metas_dom)

    # Create and return table
    out_data = Table.from_list(domain=domain, rows=rows)
    return out_data
