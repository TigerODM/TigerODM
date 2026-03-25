import copy
import spacy
from spacy.tokenizer import Tokenizer
from spacy.util import compile_infix_regex
from spacy.symbols import ORTH
# import re
from unidecode import unidecode

from Orange.data import StringVariable, DiscreteVariable, Domain, Table

pos_tags = ["ADJ", "ADP", "ADV", "AUX", "CCONJ", "DET", "INTJ", "NOUN", "NUM", "PART", "PRON", "PROPN", "PUNCT",
            "SCONJ", "SYM", "VERB", "X", "REF"]


def custom_tokenizer(nlp):
    tokenizer = Tokenizer(nlp.vocab)

    # Add custom rule to avoid splitting words that contain numbers
    # This pattern matches any word that contains at least one number (with optional symbols)
    tokenizer.add_special_case(r'\b[A-Za-z0-9#.-]+\b', [{ORTH: "@"}])  # Treat these as a single token

    return tokenizer


def create_lemmes_and_tags(table, model_path, request=False, progress_callback=None, argself=None):
    if request:
        out_data = create_lemmes_and_tags_on_request(table, model_path)
    else:
        out_data = create_lemmes_and_tags_on_text(table, model_path, progress_callback, argself)
    return out_data


def create_lemmes_and_tags_on_text(table, model_path, progress_callback=None, argself=None):
    """
    Add lemmes and tags columns to an input Data Table.

    Parameters:
    table (Table): The input Table to process.
    model_path (str): The path to the NLP model.

    Returns:
    out_data (Table): Copy of the input Table with 2 additional columns - lemmes and tags
    """
    # Copy of input data
    data = copy.deepcopy(table)
    attr_dom = list(data.domain.attributes)
    metas_dom = list(data.domain.metas)
    class_dom = list(data.domain.class_vars)
    # Load the model
    model = spacy.load(model_path)
    # Generate lemmes & tags on column named "content"
    rows = []
    for i, row in enumerate(data):
        features = list(data[i])
        metas = list(data.metas[i])
        lemmes, tags = lemmatize(str(row["content"]), model)
        lemmes = [" ".join(lemmes)]
        tags = [" ".join(tags)]
        metas += lemmes
        metas += tags
        rows.append(features + metas)
        if progress_callback is not None:
            progress_value = float(100 * (i + 1) / len(data))
            progress_callback(progress_value)
        if argself is not None:
            if argself.stop:
                break
    # Generate new Domain to add to data
    var_lemmes = StringVariable(name="Lemmes")
    var_tags = StringVariable(name="Tags")
    domain = Domain(attributes=attr_dom, metas=metas_dom + [var_lemmes, var_tags], class_vars=class_dom)
    # Create and return table
    out_data = Table.from_list(domain=domain, rows=rows)
    return out_data


def create_lemmes_and_tags_on_request(table, model_path):
    # Assume the input Table contains only one row for the request
    request = table[0]["content"].value
    # Load the model
    model = spacy.load(model_path)
    # Generate lemmes & tags
    lemmes, tags = lemmatize(request, model)
    # Rearrange lemmes and tags to fit in a Table
    rows = [[tags[i], lemmes[i]] for i in range(len(lemmes))]
    # Create domain
    var_lemmes = StringVariable(name="Lemmes")
    var_tags = DiscreteVariable(name="Tags", values=pos_tags)
    domain = Domain(attributes=[var_tags], metas=[var_lemmes])
    # Create and return Table
    out_data = Table.from_list(domain=domain, rows=rows)
    return out_data


def normalize_text(text):
    """
    Normalize text by removing accents and converting to lowercase using `unidecode`.

    Args:
        text (str): Input text.

    Returns:
        str: Normalized text.
    """
    return unidecode(text).lower()  # Convert accents and lowercase


def lemmatize(text, model):
    """
    Computes the lemmas & tags of a text using a spaCy model.
    Reference numbers (tokens with digits) are tagged as 'REF' and kept as-is.

    Parameters:
    text (str): The text to process.
    model (spacy.language.Language): The spaCy model to use for processing.

    Returns:
    tuple: Two lists containing the lemmas and tags of each token.
    """
    lemmes = []
    tags = []
    # Modify the infix patterns (patterns for token splits)
    infixes = list(model.Defaults.infixes)
    # Add custom pattern for numbers with special characters
    infixes.append(r"(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]+(?:[-.#][A-Za-z\d]+)*")
    infixes.append(r"[^\s]*")
    # Recompile the infix pattern after adding the custom one
    model.tokenizer.infix_finditer = compile_infix_regex(infixes).finditer
    document = model(text)
    for token in document:
        if any([c.isdigit() for c in token.text]):
            tags.append("REF")
            lemmes.append(token.text)  # Keep original text for reference numbers
        else:
            lemmes.append(normalize_text(token.lemma_))
            if token.pos_ not in pos_tags:
                tags.append("X")
            else:
                tags.append(token.pos_)
    return lemmes, tags

