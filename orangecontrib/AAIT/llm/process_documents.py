import os
import json
import ntpath
from pathlib import Path

from Orange.data import Table, Domain, StringVariable

import fitz
import docx
import pptx
from docx.oxml.ns import qn
from pptx.enum.shapes import MSO_SHAPE_TYPE



def process_documents(dirpath):
    if dirpath is None or not os.path.exists(dirpath):
        return None, None

    # get path from user selection
    embeddings = check_for_embeddings(dirpath)
    dirpath = dirpath.replace("\\","/")

    # Set selected path in the saved embeddings
    if embeddings is not None:
        common_path = find_common_root(embeddings).replace("\\","/")
        for row in embeddings:
            row["path"] = row["path"].value.replace("\\","/").replace(common_path, dirpath)

    # Verify which files are already processed
    files_to_process = get_files_to_process(dirpath, embeddings)

    rows = []
    for file in files_to_process:
        # Get the text content from the file
        content = extract_text(file)
        filename = ntpath.basename(file)
        # Build a row containing dirpath | filename | content
        row = [file, filename, content]
        rows.append(row)

    # Build a table with the constructed rows
    path_var = StringVariable("path")
    name_var = StringVariable("name")
    content_var = StringVariable("content")
    domain = Domain(attributes=[], metas=[path_var, name_var, content_var])
    out_data = Table.from_list(domain=domain, rows=rows)
    return out_data, embeddings


def find_common_root(data_table, column_name="path"):
    """Finds the common root path from a column of file paths in an Orange Data Table."""
    paths = [str(row[column_name]) for row in data_table if row[column_name] is not None]
    if not paths:
        return ""
    return os.path.commonpath(paths)


def get_files_to_process(folder_path, table=None):
    """
    Finds all PDF files in a folder (including subfolders) that are not already in the table.
    The comparison is based on "name" (relative path from the main folder) instead of full paths.

    :param folder_path: Path to the folder to scan for documents.
    :param table: Orange Data Table with columns "path", "name", and "content".
    :return: List of paths to files not present in the table (by name, including subfolder structure).
    """
    #TODO
    # Supported file extensions
    supported_extensions = [".pdf", ".docx"]

    # Read the json containing file sizes
    filepath_sizes = os.path.join(folder_path, "sizes.json")
    if os.path.exists(filepath_sizes):
        with open(filepath_sizes, "r") as json_file:
            sizes = json.load(json_file)
    else:
        sizes = dict()

    # Extract the existing file names from the Orange Data Table
    if table:
        existing_paths = set(table[:, "path"].metas.flatten())  # Extract names from the table
    else:
        existing_paths = set()


    # Walk through the folder and its subfolders
    new_files = []
    for root, _, files in os.walk(folder_path):
        for file in files:
            # Check if the file has a supported extension
            if os.path.splitext(file)[1].lower() in supported_extensions:
                # Add the file if it is not already in the table
                filepath = os.path.join(root, file).replace("\\","/")
                if filepath not in existing_paths:
                    new_files.append(filepath)
                    sizes[filepath] = os.path.getsize(filepath)
                # If the file is in the table, verify if the file has been modified (comparing the size)
                else:
                    new_size = os.path.getsize(filepath)
                    if filepath not in sizes.keys():
                        sizes[filepath] = new_size
                    else:
                        old_size = sizes[filepath]
                        if old_size != new_size:
                            new_files.append(filepath)
                            table = remove_from_table(filepath, table)
                            sizes[filepath] = new_size
    with open(filepath_sizes, "w") as json_file:
        json.dump(sizes, json_file, indent=4)
    return new_files


def remove_from_table(filepath, table):
    filtered_table = Table.from_list(domain=table.domain,
                                      rows=[row for row in table if row["path"].value != filepath])
    return filtered_table


def check_for_embeddings(folder_path):
    """
    Check for an embeddings.pkl file in a given folder. Return its content if it exists.

    Parameters:
        folder_path (str): The path to the folder where embeddings.pkl may exist.

    Returns:
        Table or None: The content of embeddings.pkl.
    """
    filepaths = [os.path.join(folder_path, "embeddings_question.pkl"),
                 os.path.join(folder_path, "embeddings.pkl")]
    for filepath in filepaths:
        if os.path.exists(filepath):
            data = Table.from_file(filepath)
            return data
    else:
        return None


def load_documents_in_table(table, progress_callback=None, argself=None):
    """
    Load the text content of each document listed in a table and add it
    as a new column "content".

    :param table: Orange.data.Table containing file paths in a column named "path".
    :return: Orange.data.Table with an added meta column "content" containing the extracted text.
    """
    # Make a copy of the table to avoid modifying the original
    data = table.copy()

    # List to store text from each document
    texts = []
    names = []
    # Iterate over all rows in the table
    for i, row in enumerate(data):
        # Get file path from the "path" column
        filepath = row["path"].value
        # Get text and name
        name = Path(filepath).name
        text = extract_text(filepath)
        # Store results
        names.append(name)
        texts.append(text)
        # Update progress if a callback is provided
        if progress_callback is not None:
            progress_value = float(100 * (i + 1) / len(data))
            progress_callback(progress_value)
        # Check if processing should be stopped
        if argself is not None and getattr(argself, "stop", False):
            break

    # Create a StringVariable for the new column
    var_content = StringVariable("content")
    var_name = StringVariable("name")

    # Add the column as a meta-column in the table
    data = data.add_column(variable=var_name, data=names, to_metas=True)
    data = data.add_column(variable=var_content, data=texts, to_metas=True)
    return data


def load_documents_in_table_detailed(table, progress_callback=None, argself=None):
    """
    Load the content of each document listed in a table.

    Returns a tuple (main_table, details_table):
      - main_table   : one row per file (same as load_documents_in_table),
                       columns: path, name, content
      - details_table: one row per Word object (paragraph, heading, table, …)
                       for .docx files; one row with type "document" for others,
                       columns: path, name, type, content

    :param table: Orange.data.Table containing file paths in a column named "path".
    :return: (Orange.data.Table, Orange.data.Table)
    """
    main_rows = []
    detail_rows = []
    total = len(table)

    for i, row in enumerate(table):
        filepath = row["path"].value
        name = Path(filepath).name
        ext = os.path.splitext(filepath)[1].lower()

        # --- Main table: one row per file, full text content ---
        full_text = extract_text(filepath)
        main_rows.append([filepath, name, full_text])

        # --- Details table: one row per Word object ---
        if ext == ".docx":
            objects = extract_docx_objects(filepath)
            for obj_type, content in objects:
                detail_rows.append([filepath, name, obj_type, content])
        # To include other files in the details table under type document uncomment:
        #else:
        #    detail_rows.append([filepath, name, "document", full_text])

        if progress_callback is not None:
            progress_callback(float(100 * (i + 1) / total))

        if argself is not None and getattr(argself, "stop", False):
            break

    # Build main_table (path, name, content)
    path_var = StringVariable("path")
    name_var = StringVariable("name")
    content_var = StringVariable("content")
    main_domain = Domain(attributes=[], metas=[path_var, name_var, content_var])
    main_table = Table.from_list(domain=main_domain, rows=main_rows)

    # Build details_table (path, name, type, content)
    detail_domain = Domain(
        attributes=[],
        metas=[
            StringVariable("path"),
            StringVariable("name"),
            StringVariable("type"),
            StringVariable("content"),
        ]
    )
    details_table = Table.from_list(domain=detail_domain, rows=detail_rows)

    return main_table, details_table

def _extract_header_footer_text(header_or_footer) -> str:
    """
    Extract text from a header or footer, including:
    - Static runs
    - Field code results (e.g. STYLEREF which renders the current section/heading name)
    - Table content (headers/footers often use tables for layout)
    """
    parts = []

    def _extract_from_paragraphs(paragraphs):
        para_lines = []
        for para in paragraphs:
            para_parts = []

            for child in para._element.iter():
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

                if tag == "t":
                    text = child.text or ""
                    if text.strip():
                        para_parts.append(text)

            line = "".join(para_parts).strip()
            if line:
                para_lines.append(line)
        return para_lines

    # Direct paragraphs in the header/footer
    parts.extend(_extract_from_paragraphs(header_or_footer.paragraphs))

    # Tables inside the header/footer
    for table in header_or_footer.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.extend(_extract_from_paragraphs(cell.paragraphs))

    return "\n".join(parts)


def extract_docx_objects(docx_path):
    """
    Extract Word objects from a .docx file, preserving document order.
    Returns a list of (type, content) tuples.

    Types returned:
      - "heading_N"          for Heading N styles (N = 1..9)
      - "title"              for Title style paragraphs
      - "subtitle"           for Subtitle style paragraphs
      - "paragraph"          for normal body paragraphs
      - "table"              for tables (tab/newline-separated text)
      - "header"             for default/odd-page headers (includes STYLEREF section names)
      - "header_first"       for first-page headers (page 1)
      - "header_even"        for even-page headers
      - "footer"             for default/odd-page footers
      - "footer_first"       for first-page footers (page 1)
      - "footer_even"        for even-page footers
      - "textbox"            for floating text boxes / shapes
      - "footnote"           for footnotes
      - "endnote"            for endnotes

    :param docx_path: Path to the .docx file.
    :return: List of (type_str, content_str) tuples.
    """
    try:
        doc = docx.Document(docx_path)
        objects = []

        # ------------------------------------------------------------------ #
        # 1. Headers & Footers (all variants, deduplicated by text)           #
        # ------------------------------------------------------------------ #
        seen_header_footer = set()

        def _add_hf(label, header_or_footer):
            text = _extract_header_footer_text(header_or_footer).strip()
            if text and text not in seen_header_footer:
                seen_header_footer.add(text)
                objects.append((label, text))

        for section in doc.sections:
            try:
                if section.header:
                    _add_hf("header", section.header)
                if section.footer:
                    _add_hf("footer", section.footer)
                if section.first_page_header:
                    _add_hf("header_first", section.first_page_header)
                if section.first_page_footer:
                    _add_hf("footer_first", section.first_page_footer)
                if section.even_page_header:
                    _add_hf("header_even", section.even_page_header)
                if section.even_page_footer:
                    _add_hf("footer_even", section.even_page_footer)
            except Exception as e:
                print(f"[AVERTISSEMENT] Section header/footer ignorée dans '{docx_path}': {e}")
                continue

        # ------------------------------------------------------------------ #
        # 2. Footnotes                                                         #
        # ------------------------------------------------------------------ #
        try:
            footnotes_part = doc.part.footnotes_part
            if footnotes_part is not None:
                for fn in footnotes_part._element.findall(qn("w:footnote")):
                    fn_id = fn.get(qn("w:id"), "")
                    if fn_id in ("-1", "0"):
                        continue
                    run_texts = []
                    for p in fn.findall(".//" + qn("w:p")):
                        para_text = "".join(
                            r.text for r in p.findall(".//" + qn("w:t")) if r.text
                        ).strip()
                        if para_text:
                            run_texts.append(para_text)
                    combined = " ".join(run_texts)
                    if combined:
                        objects.append(("footnote", combined))
        except Exception:
            pass

        # ------------------------------------------------------------------ #
        # 3. Endnotes                                                          #
        # ------------------------------------------------------------------ #
        try:
            endnotes_part = doc.part.endnotes_part
            if endnotes_part is not None:
                for en in endnotes_part._element.findall(qn("w:endnote")):
                    en_id = en.get(qn("w:id"), "")
                    if en_id in ("-1", "0"):
                        continue
                    run_texts = []
                    for p in en.findall(".//" + qn("w:p")):
                        para_text = "".join(
                            r.text for r in p.findall(".//" + qn("w:t")) if r.text
                        ).strip()
                        if para_text:
                            run_texts.append(para_text)
                    combined = " ".join(run_texts)
                    if combined:
                        objects.append(("endnote", combined))
        except Exception:
            pass

        # ------------------------------------------------------------------ #
        # 4. Body: paragraphs, tables, text boxes in document order           #
        # ------------------------------------------------------------------ #
        parent = doc.element.body
        table_elements = {t._element: t for t in doc.tables}
        para_elements = {p._element: p for p in doc.paragraphs}

        def _style_to_type(style_name: str) -> str:
            """Map a paragraph style name to an object type string."""
            if not style_name:
                return "paragraph"
            s = style_name.lower().strip()
            if s.startswith("heading"):
                try:
                    level = int(style_name.split()[-1])
                except ValueError:
                    level = 1
                return f"heading_{level}"
            if s == "title":
                return "title"
            if s == "subtitle":
                return "subtitle"
            return "paragraph"


        def _collect_textboxes(element) -> list:
            """
            Recursively find all text-box / shape text inside an element.
            Returns a list of ("textbox", text) tuples.
            """
            results = []
            for txbx in element.findall(".//" + qn("w:txbxContent")):
                parts = []
                for p in txbx.findall(qn("w:p")):
                    line = "".join(
                        r.text for r in p.findall(".//" + qn("w:t")) if r.text
                    ).strip()
                    if line:
                        parts.append(line)
                text = "\n".join(parts)
                if text:
                    results.append(("textbox", text))
            return results

        for child in parent.iterchildren():
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            try:
                if tag == "p":
                    # Inline text boxes / shapes
                    for tb_type, tb_text in _collect_textboxes(child):
                        objects.append((tb_type, tb_text))

                    para = para_elements.get(child)
                    if para is None:
                        continue

                    # para.text can miss runs; fall back to joining all w:t elements
                    text = para.text.strip()
                    if not text:
                        text = "".join(
                            r.text for r in child.findall(".//" + qn("w:t")) if r.text
                        ).strip()
                    if not text:
                        continue

                    style_name = para.style.name if para.style else ""
                    obj_type = _style_to_type(style_name)
                    objects.append((obj_type, text))

                elif tag == "tbl":
                    table = table_elements.get(child)
                    if table is None:
                        continue
                    table_text = _extract_table_text(table)
                    if table_text.strip():
                        objects.append(("table", table_text.strip()))

                elif tag == "sdt":
                    # Structured Document Tags (content controls: TOC, cover fields, etc.)
                    parts = []
                    for p in child.findall(".//" + qn("w:p")):
                        line = "".join(
                            r.text for r in p.findall(".//" + qn("w:t")) if r.text
                        ).strip()
                        if line:
                            parts.append(line)
                    combined = "\n".join(parts)
                    if combined:
                        objects.append(("paragraph", combined))
                    
            except Exception as e:
                print(f"[AVERTISSEMENT] Élément '{tag}' ignoré dans '{docx_path}': {e}")
                continue

        return objects

    except Exception as e:
        print(f"Error extracting objects from {docx_path}: {e}")
        return [("document", f"ERROR: Extraction Error ({e})")]


def _extract_table_text(table) -> str:
    """Convert a table to tab/newline-separated text, en ignorant les cellules/lignes cassées."""
    rows = []
    try:
        table_rows = table.rows
    except Exception as e:
        print(f"[AVERTISSEMENT] Tableau ignoré (structure invalide): {e}")
        return ""

    for row in table_rows:
        cells = []
        try:
            row_cells = row.cells
        except Exception as e:
            print(f"[AVERTISSEMENT] Ligne ignorée (structure invalide): {e}")
            continue
        for cell in row_cells:
            try:
                cells.append(cell.text.strip())
            except Exception as e:
                print(f"[AVERTISSEMENT] Cellule ignorée: {e}")
                cells.append("")
        rows.append("\t".join(cells))
    return "\n".join(rows)


def extract_text(filepath):
    """
    Extrait le texte d'un fichier en fonction de son type (PDF ou DOCX).

    :param filepath: Chemin vers le fichier.
    :return: Texte extrait du fichier sous forme de chaîne.
    """
    try:
        # Vérifie l'extension du fichier
        file_extension = os.path.splitext(filepath)[1].lower()
        print(file_extension)

        if file_extension == ".pdf":
            return extract_text_from_pdf(filepath)
        elif file_extension == ".docx":
            return extract_text_from_docx(filepath)
        elif file_extension == ".pptx":
            return extract_text_from_pptx(filepath)
        elif file_extension in [".txt", ".md", ".py", ".html", ".json", ".ows"]:
            return extract_text_from_txt(filepath)
        else:
            return "ERROR: Unsupported file format. Please use a .pdf, .docx, pptx, .txt, .md, .py, .html, .ows or .json file."
    except Exception as e:
        print(f"Erreur lors de l'extraction de texte depuis {filepath}: {e}")
        return f"ERROR: Extraction Error ({e})"


def extract_text_from_pdf(pdf_path):
    """
    Extrait le texte d'un fichier PDF.

    :param pdf_path: Chemin vers le fichier PDF.
    :return: Texte extrait du PDF sous forme de chaîne.
    """
    try:
        # Ouvre le fichier PDF
        pdf_document = fitz.open(pdf_path)
        extracted_text = ""

        # Parcourt toutes les pages et extrait le texte
        for page_num in range(len(pdf_document)):
            page = pdf_document[page_num]
            extracted_text += page.get_text()

        pdf_document.close()
        return extracted_text
    except Exception as e:
        print(f"Erreur lors de l'extraction de texte depuis {pdf_path}: {e}")
        return f"ERROR: Extraction Error ({e})"


def extract_text_from_docx(docx_path):
    """
    Extrait le texte d'un fichier DOCX en conservant l'ordre des éléments (paragraphes, tableaux et titres).

    :param docx_path: Chemin vers le fichier DOCX.
    :return: Texte extrait du document sous forme de chaîne.
    """
    try:
        doc = docx.Document(docx_path)
        extracted_text = []
        title_numbers = {}  # Dictionary to track numbering per heading level

        for para in doc.paragraphs:
            # Vérifie si c'est un titre
            if para.style.name.startswith('Heading'):
                heading_level = int(para.style.name.split()[-1])  # Niveau du titre (1, 2, 3, etc.)
                heading_text = para.text.strip()

                # Met à jour la numérotation des titres
                if heading_level not in title_numbers:
                    title_numbers[heading_level] = 1  # Nouveau niveau
                else:
                    title_numbers[heading_level] += 1  # Incrémente niveau actuel

                # Réinitialise les niveaux inférieurs
                for level in list(title_numbers.keys()):
                    if level > heading_level:
                        del title_numbers[level]

                # Forme le numéro du titre (ex: "1", "1.1", "1.2.1")
                full_title = ".".join(str(title_numbers[i]) for i in sorted(title_numbers.keys()))
                extracted_text.append(f"\n{full_title} {heading_text}")  # Ajoute le titre formaté
            else:
                extracted_text.append(para.text.strip())  # Ajoute le paragraphe

        # Parcourt les tableaux du document
        for table_idx, table in enumerate(doc.tables):
            table_text = []
            try:
                rows = table.rows
            except Exception as e:
                print(f"[AVERTISSEMENT] Tableau {table_idx + 1} ignoré (structure invalide) dans '{docx_path}': {e}")
                continue

            for row_idx, row in enumerate(rows):
                try:
                    row_text = [cell.text.strip() for cell in row.cells]
                    table_text.append("\t".join(row_text))
                except Exception as e:
                    print(f"[AVERTISSEMENT] Tableau {table_idx + 1}, ligne {row_idx + 1} ignorée dans '{docx_path}': {e}")
                    continue

            extracted_text.append("\n".join(table_text))      
    
    except Exception as e:
        print(f"Erreur lors de l'extraction de texte depuis {docx_path}: {e}")
        return f"ERROR: Extraction Error ({e})"

    return "\n".join(filter(None, extracted_text))  # Retourne le texte en filtrant les vides


def extract_text_from_txt(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"Erreur lors de l'extraction de texte depuis {filepath}: {e}")
        return f"ERROR: Extraction Error ({e})"


def extract_text_from_pptx(filepath):
    try:
        prs = pptx.Presentation(filepath)
        full_text = []

        def walk_shapes(shapes):
            text_bits = []
            for shape in shapes:
                # 1. Standard text shapes
                if hasattr(shape, "text") and shape.text.strip() and not shape.has_table:
                    text_bits.append(shape.text)

                # 2. Tables converted to Markdown
                elif shape.has_table:
                    table_md = []
                    rows = list(shape.table.rows)
                    if not rows:
                        continue

                    for row_idx, row in enumerate(rows):
                        # Extract text from each cell, replace newlines with spaces to keep MD table valid
                        cells = [cell.text.replace('\n', ' ').strip() for cell in row.cells]
                        table_md.append(f"| {' | '.join(cells)} |")

                        # Add the Markdown separator after the first row (header)
                        if row_idx == 0:
                            separator = f"| {' | '.join(['---'] * len(cells))} |"
                            table_md.append(separator)

                    text_bits.append("\n" + "\n".join(table_md) + "\n")

                # 3. Grouped shapes
                elif shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                    text_bits.extend(walk_shapes(shape.shapes))

            return text_bits

        for i, slide in enumerate(prs.slides):
            full_text.append(f"### Slide n°{i + 1}")
            slide_content = walk_shapes(slide.shapes)
            full_text.extend(slide_content)
            full_text.append("\n---\n")  # Visual separator in Markdown
        return "\n".join(full_text)

    except Exception as e:
        return f"ERROR: Extraction Error ({e})"


def get_pages_of_extract(pdf_path, extract):
    """
    Identify the pages that a given extract belongs to.

    :param pdf_path: The path of the pdf to search in.
    :param extract: The text snippet to locate.
    :return: A list of page numbers the extract spans.
    """
    full_text, page_mapping = load_pdf_with_sparse_mapping(pdf_path)
    # Find the start index of the extract in the full text
    start_index = full_text.find(extract)
    if start_index == -1:
        return []  # Extract not found

    # Determine the end index of the extract
    end_index = start_index + len(extract) - 1

    # Find all pages the extract spans
    pages = []
    for page, (start, end) in page_mapping.items():
        if start <= end_index and end >= start_index:
            pages.append(page)

    if pages == []:
        return [1]
    return pages


def load_pdf_with_sparse_mapping(pdf_path):
    doc = fitz.open(pdf_path)
    full_text = ""
    page_mapping = {}  # Sparse mapping: {page_num: (start_index, end_index)}

    for page_num in range(len(doc)):
        page_text = doc[page_num].get_text()
        start_index = len(full_text)
        full_text += page_text
        end_index = len(full_text) - 1
        page_mapping[page_num + 1] = (start_index, end_index)

    doc.close()
    return full_text, page_mapping
