import copy

from Orange.data import ContinuousVariable, Domain, Table


def create_embeddings(table, model, column_name, widget_object=None, progress_callback=None, argself=None):
    if len(table) == 0:
        return None
    # Copy of input data
    data = copy.deepcopy(table)
    attr_dom = list(data.domain.attributes)
    metas_dom = list(data.domain.metas)
    class_dom = list(data.domain.class_vars)

    # Get tokenizer to measure input
    tokenizer = model.tokenizer
    max_length = model.get_max_seq_length()

    # Generate embeddings on column named "content"
    embeddings = None
    rows = []
    for i, row in enumerate(data):
        features = [row[x] for x in attr_dom]
        targets = [row[y] for y in class_dom]
        metas = list(data.metas[i])
        text = str(row[column_name])
        if widget_object is not None:
            encoded = tokenizer(text, add_special_tokens=True, truncation=False)
            nb_tokens = len(encoded["input_ids"])
            if nb_tokens > max_length:
                widget_object.warning(f"The text you are trying to embed ({nb_tokens} tokens) is longer than the maximum length supported by this model ({max_length} tokens).")

        embeddings = model.encode(text, show_progress_bar=False)
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