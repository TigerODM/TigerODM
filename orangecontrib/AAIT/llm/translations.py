import copy
from threading import Thread

from Orange.data import Domain, StringVariable, Table
from transformers import TextIteratorStreamer


def generate_translation(table, model, tokenizer, progress_callback=None, argself=None):
    """
    generate a translation
    input : datas in content column in a table
    output : input table with translation in "Translation" column
    """
    # Copy of input data
    data = copy.deepcopy(table)
    attr_dom = list(data.domain.attributes)
    metas_dom = list(data.domain.metas)
    class_dom = list(data.domain.class_vars)

    # Generate translation on column named "content"
    try:
        rows = []
        for i, row in enumerate(data):
            features = list(data[i])
            metas = list(data.metas[i])
            translation = translate(str(row["content"]), model=model, tokenizer=tokenizer, stream=True,
                                    argself=argself)
            metas += [translation]
            rows.append(features + metas)
            if progress_callback is not None:
                progress_value = float(100 * (i + 1) / len(data))
                progress_callback(progress_value)
            if argself is not None:
                if argself.stop:
                    break
    except ValueError as e:
        print("An error occurred when trying to generate a translation:", e)
        return

    # Generate new Domain to add to data
    var_name = "Translation"
    count = 1
    while var_name in data.domain:
        var_name = f"Translation ({count})"
        count += 1
    answer_dom = [StringVariable(var_name)]

    # Create and return table
    domain = Domain(attributes=attr_dom, metas=metas_dom + answer_dom, class_vars=class_dom)
    out_data = Table.from_list(domain=domain, rows=rows)
    return out_data


def translate(text, model, tokenizer, stream=False, argself=None):

    # FORCER LE MODELE SUR CPU
    device = "cpu"
    try:
        model.to(device)
    except Exception:
        pass

    tokenized_text = tokenizer(
        [text],
        return_tensors="pt",
        truncation=True,
        max_length=512
    )

    # FORCER LES TENSEURS SUR CPU
    tokenized_text = {k: v.to(device) for k, v in tokenized_text.items()}

    if not stream:
        tokenized_translated = model.generate(
            **tokenized_text,
            max_new_tokens=512
        )

        translated_text = tokenizer.decode(
            tokenized_translated[0],
            skip_special_tokens=True,
            truncation=True
        )

    else:
        streamer = TextIteratorStreamer(tokenizer, skip_special_tokens=True)

        generation_kwargs = dict(
            **tokenized_text,
            streamer=streamer,
            max_new_tokens=512,
            num_beams=1
        )

        thread = Thread(target=model.generate, kwargs=generation_kwargs)
        thread.start()

        translated_text = ""

        for token in streamer:
            translated_text += token
            if argself is not None and argself.stop:
                break

    return translated_text
