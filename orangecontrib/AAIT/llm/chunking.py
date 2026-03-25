import os
import Orange
from Orange.data import Domain, Table, StringVariable, ContinuousVariable
from sentence_transformers import SentenceTransformer

### Chonkie
from chonkie import TokenChunker, SentenceChunker, RecursiveChunker, SemanticChunker, LateChunker, CodeChunker
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.llm import wordchunker_deprecated
    from Orange.widgets.orangecontrib.AAIT.utils.MetManagement import get_local_store_path
else:
    from orangecontrib.AAIT.llm import wordchunker_deprecated
    from orangecontrib.AAIT.utils.MetManagement import get_local_store_path


def create_chunks(table, column_name, tokenizer="character", chunk_size=300, chunk_overlap=100, mode="tokens",
                  progress_callback=None, argself=None):
    """
    Chunk the text in `column_name` of an Orange Table using a specialized chunker.

    Splits each row's text into chunks based on the selected mode (Token, Sentence,
    Recursive, or Markdown). Adds the chunked text and its metadata as new meta
    columns to the table.

    Parameters:
        table (Table): Input data table.
        column_name (str): Name of the text column to chunk.
        tokenizer (str): Tokenizer type (e.g., "character").
        chunk_size (int): Target chunk size.
        chunk_overlap (int): Overlap between chunks (not used in all modes).
        mode (str): Chunking strategy ("Token", "Sentence", "Recursive", "Markdown").
        progress_callback (callable): Optional progress reporter.
        argself: Optional caller reference.

    Returns:
        Table: The table with added meta columns: "Chunks", "Chunks size", and "Metadata".
    """

    model_name = os.path.basename(tokenizer.name_or_path) if hasattr(tokenizer, "name_or_path") else "character"

    # Définir la fonction de chunking selon le mode
    if mode == "tokens":
        chunker = TokenChunker(tokenizer=tokenizer, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    elif mode == "words":
        path_ugly = os.path.join(get_local_store_path(), "Models", "NLP", "all-mpnet-base-v2")
        tokenizer = SentenceTransformer(path_ugly, device="cpu")
        model_name = "MPNET"
        chunker = wordchunker_deprecated.WordChunker(tokenizer=tokenizer, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    elif mode == "sentence":
        chunker = SentenceChunker(tokenizer=tokenizer, chunk_size=chunk_size, chunk_overlap=chunk_overlap,
                                  min_sentences_per_chunk=1)
    elif mode == "markdown":
        markdown_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources/markdown_recipe.json")
        chunker = RecursiveChunker.from_recipe(path=markdown_path,
                                               tokenizer=tokenizer,
                                               chunk_size=chunk_size,
                                               min_characters_per_chunk=1)

    # TODO : Ajouter la gestion des paramètres dans le .ui
    # Nécessite des "rules" pour faire un chunking différent de Token ou Sentence
    elif mode == "Recursive":
        chunker = RecursiveChunker(tokenizer=tokenizer, chunk_size=chunk_size, min_characters_per_chunk=24)
    # À tester avant d'ajouter la fonctionnalité dans l'UI
    # Model d'embeddings REQUIS !
    elif mode == "Semantic":
        chunker = SemanticChunker(embedding_model=tokenizer, threshold=0.7, chunk_size=chunk_size, similarity_window=3)
    # À tester avant d'ajouter la fonctionnalité dans l'UI
    # Model d'embeddings REQUIS !
    elif mode == "Late":
        chunker = LateChunker(embedding_model=tokenizer, chunk_size=chunk_size, min_characters_per_chunk=24)
    elif mode == "Code":
        chunker = CodeChunker("blabla")
    else:
        raise ValueError(f"Invalid mode: {mode}. Valid modes are: Token, Sentence, Recursive, Markdown")

    new_metas = list(table.domain.metas) + [StringVariable("Chunks"),
                                            ContinuousVariable("Chunks size"),
                                            ContinuousVariable("Chunks index"),
                                            StringVariable("Metadata")]
    metas_infos = [ContinuousVariable("Overlap"),
                   StringVariable("Chunking model"),
                   StringVariable("Chunking method")]

    new_domain = Domain(table.domain.attributes, table.domain.class_vars, new_metas)
    new_domain_info = Domain([], metas=metas_infos)

    new_rows = []
    info_rows = []
    for i, row in enumerate(table):
        content = row[column_name].value
        chunks = chunker(content)
        # For each chunk in the chunked data
        for j, chunk in enumerate(chunks):
            # Build new metas with previous data and the chunk
            new_metas_values = list(row.metas) + [chunk.text,
                                                  chunk.token_count,
                                                  j, # Chunks index
                                                  ""]
            info_rows.append([chunk_overlap, model_name, mode])
            # Create the new row instance
            new_instance = Orange.data.Instance(new_domain,
                                                [row[x] for x in table.domain.attributes] + [row[y] for y in
                                                                                             table.domain.class_vars] + new_metas_values)
            # Store the new row
            new_rows.append(new_instance)

        if progress_callback is not None:
            progress_value = float(100 * (i + 1) / len(table))
            progress_callback(progress_value)
        if argself is not None:
            if argself.stop:
                break

    return Table.from_list(domain=new_domain, rows=new_rows), Table.from_list(domain=new_domain_info, rows=info_rows)