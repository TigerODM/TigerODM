import fitz  # PyMuPDF
import os
import re
import ast
import json
import tqdm
import copy
import difflib
import sys
import subprocess
import shutil
from json_repair import repair_json
from pathlib import Path
import hashlib


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.llm import prompt_management
    from Orange.widgets.orangecontrib.AAIT.llm.answers_llama import run_Qwen3VL_query, run_query, split_think, count_tokens
else:
    from orangecontrib.AAIT.llm import prompt_management
    from orangecontrib.AAIT.llm.answers_llama import run_Qwen3VL_query, run_query, split_think, count_tokens

# ==========================================================
# CENTRALIZED DOCUMENT PREPARATION
# ==========================================================
def prepare_document_for_pdf_ops(path, cache_dir=None, keep_converted=True):
    """
    Returns a PDF path usable by PyMuPDF.

    If input is already a PDF -> returns original path.
    If input is docx/pptx/doc/ppt -> converts once and reuses file.

    Parameters
    ----------
    path : str | Path
    cache_dir : str | Path | None
        Where converted PDFs are stored.
        Default: sibling folder '_pdf_cache'
    keep_converted : bool
        If False, caller may delete later manually.

    Returns
    -------
    pdf_path : Path
    created_temp : bool
        True if conversion happened
    """
    path = Path(path).resolve()
    ext = path.suffix.lower()

    if ext == ".pdf":
        return path, False

    if ext not in [".docx", ".doc", ".pptx", ".ppt"]:
        raise ValueError(f"Unsupported file type: {ext}")

    # Converted file name beside source file
    pdf_path = path.parent / f"{path.stem}.converted.pdf"

    # Reuse existing converted PDF if newer than source
    if pdf_path.exists():
        if pdf_path.stat().st_mtime >= path.stat().st_mtime:
            return pdf_path, False

    # Convert source file
    convert_to_pdf(path, pdf_path)

    return pdf_path, True

# Step 1 - Extract documents (pptx, docx, pdf) pages & convert them to images
def extract_pages(path, output_dir):
    image_paths = to_images(path, output_dir)
    text_per_page = extract_text_per_page(path)
    return image_paths, text_per_page


# Step 2 - Find the start of the document
def find_start_of_document(image_paths, model, N=15):
    first_images = image_paths[:N]
    prompt = prompts["find_start_of_document"]
    answer = run_Qwen3VL_query(query=prompt, image_paths=first_images, image_prompts=[], model=model)
    data = answer_to_json(answer)
    start = data["Start_of_Document"]
    if start == "NA":
        start = 0
    else:
        start = int(start) - 1
    return start


# Step 3 - Go through pages to identify the structure of the document
def find_document_structure(image_paths, start, model, batch_size=2, output_dir=None, label=None):
    global_structure = ""
    content_images = image_paths[start:]
    for i in range(0, len(content_images), batch_size):
        if label:
            label.setText(f"Step 2/6 - Generating a global structure - pages {i} to {min(i+batch_size, len(content_images))} out of {len(content_images)} ")
        batch = content_images[i:i + batch_size]
        # Extract page numbers from filenames
        page_numbers = [int(re.findall(r"page_(\d+)\.png", path)[0]) for path in batch]
        numbers_iter = iter(page_numbers)
        # Call the VLM to find headers
        prompt = prompts["generate_TOC"]
        answer = run_Qwen3VL_query(query=prompt, image_paths=batch, image_prompts=[], model=model)
        # Replace IMAGE X → Page X
        answer = re.sub(r"IMAGE \d+", make_replace_image(numbers_iter), answer, flags=re.IGNORECASE)
        global_structure += answer + "\n\n"

        # Immediatly free batch references
        del batch

    # After computing global_structure in the batch loop, save if demanded
    global_structure = global_structure.replace(r"\n\n", r"\n")
    if output_dir:
        with open(os.path.join(output_dir, "global_structure.txt"), "w", encoding="utf-8") as f:
            f.write(global_structure)

    return global_structure


# Step 4 - Clear the TOC from duplicates and artifacts
def clear_toc(global_structure, model, output_dir=None):
    prompt = prompts["clear_TOC"].format(TEXT=global_structure)
    prompt = prompt_management.apply_prompt_template("qwen", user_prompt=prompt, force_non_thinking=True)
    answer = run_query(prompt=prompt, model=model, max_tokens=0)
    clean_toc = split_think(answer)[1]
    clean_toc = re.sub(r"\*\* ?Table des matières ?\*\*", "", clean_toc).strip()

    if output_dir:
        with open(os.path.join(output_dir, "unstructured_toc.txt"), "w", encoding="utf-8") as f:
            f.write(clean_toc)

    return clean_toc


# Step 5 - Transform the text TOC into a JSON formatted TOC
def toc_to_json(clean_toc, model, output_dir=None):
    prompt = prompts["toc_to_json"].format(TEXT=clean_toc)
    prompt = prompt_management.apply_prompt_template("qwen", user_prompt=prompt, force_non_thinking=True)
    answer = run_query(prompt=prompt, model=model, max_tokens=0)
    json_toc_str = split_think(answer)[1]
    json_toc = answer_to_json(json_toc_str)

    if output_dir:
        with open(os.path.join(output_dir, "json_toc.json"), "w", encoding="utf-8") as f:
            json.dump(json_toc, f, ensure_ascii=False, indent=2)

    return json_toc


# Step 6 - Generate PageIndex
def generate_PageIndex(json_toc, text_per_page, output_dir=None):
    page_index = compute_toc_page_intervals(json_toc, text_per_page=text_per_page)

    if output_dir:
        with open(os.path.join(output_dir, "page_index.json"), "w", encoding="utf-8") as f:
            json.dump(page_index, f, ensure_ascii=False, indent=2)

    return page_index


# Step 7 - Generate a brief note summarizing what can be found in the document
def generate_summary(toc, name, model, output_dir=None):
    prompt = prompts["short_summary"].format(TEXT=toc, NAME=name)
    prompt = prompt_management.apply_prompt_template("qwen", user_prompt=prompt)
    answer = run_query(prompt=prompt, model=model, max_tokens=0)
    summary = split_think(answer)[1]

    if output_dir:
        with open(os.path.join(output_dir, "summary.txt"), "w", encoding="utf-8") as f:
            f.write(summary)

    return summary

# Step 7 bis - Generate a brief note summarizing what can be found in the document
def generate_summary_VLM(toc, name, image_path, model, output_dir=None):
    prompt = prompts["short_summary"].format(TEXT=toc, NAME=name)
    prompt = prompt_management.apply_prompt_template("qwen", user_prompt=prompt)
    # answer = run_query(prompt=prompt, model=model, max_tokens=0)
    answer = run_Qwen3VL_query(query=prompt, image_paths=image_path, image_prompts=[], model=model)
    summary = split_think(answer)[1]

    if output_dir:
        with open(os.path.join(output_dir, "summary.txt"), "w", encoding="utf-8") as f:
            f.write(summary)

    return summary


# Load intermediate results
def load_file(path, default=None):
    """
    Load a JSON or TXT file depending on extension.

    Args:
        path (str): Path to the file
        default: Value to return if file is missing or invalid

    Returns:
        dict / list (for JSON) or str (for TXT)
    """
    if not os.path.exists(path):
        return default

    ext = os.path.splitext(path)[1].lower()

    try:
        with open(path, "r", encoding="utf-8") as f:
            if ext == ".json":
                return json.load(f)
            elif ext == ".txt":
                return f.read()
            else:
                raise ValueError(f"Unsupported file type: {ext}")
    except (json.JSONDecodeError, OSError, ValueError):
        return default


def verify_database(database_index):
    errors = []
    for entry in database_index:
        doc_id = entry["id"]
        summary = entry["summary"]
        if summary == "An error happened !" or summary == "":
            errors.append(doc_id)
    return errors


def to_images(path, output_dir, zoom=2):
    """
    Converts each page of a PDF, pptx or docx into PNG images.

    Parameters:
    - path: str, path to the input file
    - output_dir: str, directory where images will be saved
    - zoom: int, scaling factor for resolution (default 2)

    Returns:
    - image_paths: list of str, paths to the generated image files
    """
    # Ensure output directory exists
    path = Path(path).resolve()
    os.makedirs(output_dir, exist_ok=True)

    pdf_path, _ = prepare_document_for_pdf_ops(path)

    doc = fitz.open(str(pdf_path))
    mat = fitz.Matrix(zoom, zoom)

    image_paths = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        pix = page.get_pixmap(matrix=mat)

        img_path = os.path.join(output_dir, f"page_{page_num}.png")
        pix.save(img_path)
        image_paths.append(img_path)

    doc.close()
    return image_paths

def convert_to_pdf(input_path, output_path):
    """
    Converts an Office file (Word or PowerPoint) to PDF based on the operating system with a multi-stage fallback strategy:
    1. Microsoft Office (Native)
    2. LibreOffice (Third-party)
    3. Placeholder for no-software solution
    """
    ext = input_path.suffix.lower()
    converted = False
    
    # --- 1. WINDOWS STRATEGY ---
    if sys.platform.startswith("win"):
        # Try Microsoft Office first
        try:
            import win32com.client
            is_ppt = "ppt" in ext
            app_name = "PowerPoint.Application" if is_ppt else "Word.Application"
            # Attempt to connect to the COM interface
            app = win32com.client.Dispatch(app_name)
            try:
                if is_ppt:
                    pres = app.Presentations.Open(str(input_path), WithWindow=False)
                    pres.SaveAs(str(output_path), 32)
                    pres.Close()
                else:
                    doc = app.Documents.Open(str(input_path))
                    doc.SaveAs(str(output_path), 17)
                    doc.Close()
                converted = True
            finally:
                app.Quit()
        except Exception:
            print("Microsoft Office not found or failed. Trying LibreOffice...")
            
    # --- 2. MACOS STRATEGY ---
    elif sys.platform == "darwin":
        try:
            app_name = "Microsoft PowerPoint" if "ppt" in ext else "Microsoft Word"
            script = f'tell application "{app_name}" to save (open POSIX file "{input_path}") in POSIX file "{output_path}" as PDF'
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
            converted = True
        except subprocess.CalledProcessError:
            print("Microsoft Office for Mac not found or failed. Trying LibreOffice...")

    # --- 3. UNIVERSAL FALLBACK: LIBREOFFICE (Windows, Mac, Linux) ---
    if not converted:
        # Check if LibreOffice command is available in the system PATH
        if shutil.which("libreoffice"):
            try:
                subprocess.run([
                    "libreoffice", "--headless", "--convert-to", "pdf",
                    "--outdir", str(output_path.parent), str(input_path)
                ], check=True, capture_output=True)
                converted = True
            except subprocess.CalledProcessError:
                print("LibreOffice conversion failed.")
        else:
            print("LibreOffice not found.")

    # --- 4. LAST RESORT: NO-THIRD-PARTY SOFTWARE (Placeholder) ---
    if not converted:
        # PLACEHOLDER: This is where you would implement a library like 'comtypes' (Windows only)
        # or a cloud-based conversion API, or a specialized library like 'docx2pdf' 
        # (though most of them still require Office installed).
        # For now, we raise an error.
        raise RuntimeError(f"No software found (Office or LibreOffice) to convert {input_path.name}")

    return output_path


def extract_text_per_page(path, start_page=0, end_page=None):
    """
    Extracts text from each page of a document (PDF) and returns a dict: {page_number: text}.

    Parameters:
    - path: str, path to the document
    - start_page: int, 0-based index to start extracting (default 0)
    - end_page: int, 0-based index to end extracting (exclusive, default None = till last page)

    Returns:
    - page_texts: dict mapping 0-based page number -> text
    """
    pdf_path, _ = prepare_document_for_pdf_ops(path)

    doc = fitz.open(str(pdf_path))

    page_texts = {}
    last_page = end_page if end_page is not None else len(doc)
    last_page = min(last_page, len(doc))

    for i in range(start_page, last_page):
        page = doc[i]
        text = page.get_text("text")
        page_texts[i] = text
    
    doc.close()
    return page_texts


def answer_to_json(answer):
    """
    Extracts and parses a JSON object from a markdown code block.

    Parameters:
    - answer: str, text containing a ```json ... ``` block

    Returns:
    - data: dict, parsed JSON content

    Raises:
    - ValueError: if no valid JSON block is found or parsing fails
    """
    # Find JSON code blocks
    json_matches = re.findall(r"```json([\s\S]*?)```", answer)
    # Expect exactly one JSON block
    if len(json_matches) != 1:
        raise ValueError(f"Wrong format returned by the VLM: {answer}")
    json_str = json_matches[0]
    try:
        # Attempt to repair and parse JSON
        data = json.loads(repair_json(json_str))
    except Exception:
        raise ValueError(f"JSON returned by the VLM had wrong format: {json_str}")
    return data


def make_replace_image(numbers_iter):
    # returns a function compatible with re.sub
    def replace(match):
        return f"Page {next(numbers_iter)}"

    return replace


def compute_toc_page_intervals(json_toc, text_per_page):
    """
    Compute page intervals for each TOC entry.

    Logic:
    - Deepest-level headers: interval = start page → next entry's page - 1 (any level)
    - Higher-level headers:  interval = start page → next sibling/ancestor's page - 1
                             (next entry whose level <= current level)
    """
    toc_copy = copy.deepcopy(json_toc)

    # Normalize level and page to int
    for entry in toc_copy:
        level = entry.get("level", 1)
        level = 1
        entry["level"] = int(level) if str(level).isdigit() else 1
        page = entry.get("page", 0)
        entry["page"] = int(page) if str(page).isdigit() else 0

    n_entries = len(toc_copy)
    max_level = max(entry["level"] for entry in toc_copy)
    last_page = len(text_per_page) - 1

    for i, entry in enumerate(toc_copy):
        level = entry["level"]
        page_start = entry["page"]

        if level == max_level:
            page_end = toc_copy[i + 1]["page"] if i + 1 < n_entries else last_page
        else:
            page_end = last_page
            for j in range(i + 1, n_entries):
                if toc_copy[j]["level"] <= level:
                    page_end = toc_copy[j]["page"]
                    break

        entry["pages"] = f"{page_start} - {page_end}"
        entry.pop("page", None)
        entry.pop("level_identifiable", None)

    return toc_copy


def identify_tool_call(answer):
    """
    Parse a model answer to identify if a tool should be called.

    Returns:
        tool_type: "select_document", "get_pages", or None
        args: tuple of arguments (strings or ints)
    """
    if "```tool" not in answer:
        return None, None

    tool_call = answer.split("```tool")[1].split("```")[0].strip()

    # TOOL 1: view_documents()
    match_doc = re.match(r"view_documents\((.*?)\)", tool_call)
    if match_doc:
        return "view_documents", 0

    # TOOL 2: select_document("doc_id")
    match_doc = re.match(r"select_document\((.*?)\)", tool_call)
    if match_doc:
        doc_name = match_doc.group(1).strip().strip('"').strip("'")
        return "select_document", (doc_name,)

    # TOOL 3: select(id)
    match_id = re.match(r"select\((.*?)\)", tool_call)
    if match_id:
        doc_id = match_id.group(1).strip().strip('"').strip("'")
        return "select", (doc_id,)

    # TOOL 4: get_pages(start, end)
    match_pages = re.match(r"get_pages\((\d+),\s*(\d+)\)", tool_call)
    if match_pages:
        start, end = int(match_pages.group(1)), int(match_pages.group(2))
        return "get_pages", (start, end)


    # Unknown tool
    return "Unknown tool", None



def identify_tool_call_2(answer):
    """
    Parse a model answer to identify if a tool should be called.
    Supports the <tool_call><function=...><parameter=...> template format.
    Returns:
        tool_type: "view_documents", "select_document", "select", "get_pages", or None
        args: tuple of arguments (strings or ints), or 0 for view_documents, or None
    """
    if "<tool_call>" not in answer:
        return None, None

    try:
        # Extract the <tool_call> block
        tool_call_match = re.search(r"<tool_call>(.*?)</tool_call>", answer, re.DOTALL)
        if not tool_call_match:
            return None, None
        tool_call_block = tool_call_match.group(1).strip()

        # Extract function name from <function=FUNC_NAME>
        func_match = re.search(r"<function=(\w+)>", tool_call_block)
        if not func_match:
            return "Unknown tool", None
        func_name = func_match.group(1)

        # Extract all parameters into a dict: {param_name: param_value}
        params = {}
        param_matches = re.findall(
            r"<parameter=(\w+)>(.*?)</parameter>",
            tool_call_block,
            re.DOTALL
        )
        for param_name, param_value in param_matches:
            params[param_name] = param_value.strip()

        # TOOL 1: view_documents()
        if func_name == "view_documents":
            return "view_documents", 0

        # TOOL 2: select_document("doc_id")
        elif func_name == "select_document":
            doc_name = params.get("doc_id", "")
            return "select_document", (doc_name,)

        # TOOL 3: select(id)
        elif func_name == "select":
            doc_id = params.get("unique_id", params.get("id", ""))
            return "select", (doc_id,)

        # TOOL 4: get_pages(start, end)
        elif func_name == "read_file":
            start = int(params.get("page_start", params.get("start", 0)))
            end = int(params.get("page_end", params.get("end", 0)))
            return "read_file", (start, end)

        else:
            return "Unknown tool", None

    except Exception as e:
        print(f"Parsing error: {e}")
        return "Unknown tool", None



# TOOL
def view_documents(database_index):
    documents_summaries = []
    for entry in database_index:
        documents_summaries.append({"name": entry["name"], "summary": entry["summary"]})
    document_summaries = f"{documents_summaries}"
    return document_summaries


# TOOL
def select_document(name, database_index):
    """
    Select a document by name. If exact match not found, return the most similar name.

    Parameters:
        name (str): the document name to search
        database_index (list[dict]): list of document entries with "name" keys

    Returns:
        dict: matched document entry (exact or closest)
    """
    # Try exact match first
    for entry in database_index:
        if entry["name"] == name:
            return entry

    # No exact match → find closest
    all_names = [entry["name"] for entry in database_index]
    close_matches = difflib.get_close_matches(name, all_names, n=1, cutoff=0.5)  # cutoff = similarity threshold

    if close_matches:
        # Return entry with the closest name
        closest_name = close_matches[0]
        for entry in database_index:
            if entry["name"] == closest_name:
                return entry

    # If nothing found
    return {}


# TOOL
def select(unique_id, database_index, dirpath):
    """
    Select a document or folder by id.

    Parameters:
        unique_id (int): the document id to search
        database_index (list[dict]): list of document entries with "id" keys

    Returns:
        dict: matched document entry
    """
    # Try exact match first
    unique_id = int(unique_id)
    for entry in database_index:
        if entry["unique_id"] == unique_id:
            return entry

    # 2. Walk through all subdirectories
    # Todo : revoir l'efficacité de cette logique !
    for root, dirs, files in os.walk(dirpath):
        if "database_index.json" in files:
            database_index_path = os.path.join(root, "database_index.json")

            try:
                with open(database_index_path, "r", encoding="utf-8") as f:
                    sub_index = json.load(f)
            except Exception as e:
                # Skip unreadable or invalid JSON files
                print(f"Could not load Database index:  {database_index_path}, error: {e}")
                continue

            # 3. Search inside this index
            for entry in sub_index:
                if entry.get("unique_id") == unique_id:
                    return entry


    # If nothing found
    return {}


# TOOL
def get_pages(path, start=0, end=None, limit=15):
    """
    Extract text from a document (PDF, PPTX, DOCX) for a given page range and return as a single string,
    with page headers, missing page notes, separators, and a page limit.

    Parameters:
        path (str): path to the document
        start (int): 0-based start page (inclusive)
        end (int): 0-based end page (inclusive). If None, goes to last page.
        limit (int): maximum number of pages to actually read

    Returns:
        str: concatenated text with annotations
    """
    # Extract per-page text
    pages_text = extract_text_per_page(path, start_page=start, end_page=(end + 1 if end is not None else None))

    # Determine actual end page
    last_page = end if end is not None else max(pages_text.keys())

    # Compute how many pages to read according to limit
    num_pages = last_page - start + 1
    read_pages = min(num_pages, limit)
    pages_combined = []

    for i, p in enumerate(range(start, last_page + 1)):
        if i >= read_pages:
            break  # stop reading if limit reached
        if p in pages_text:
            pages_combined.append(f"### Page {p}\n{pages_text[p]}")
        else:
            pages_combined.append(f"### Page {p}\n[Page not available]")

    # If some pages were not read due to limit, add a note
    if num_pages > limit:
        skipped_start = start + read_pages
        skipped_end = last_page
        pages_combined.append(f"### [Pages {skipped_start}-{skipped_end} were not read (limited to {limit} pages at a time). Call read_file again to access these pages.]")

    return "\n".join(pages_combined)


def clear_ephemeral_messages(ephemeral_messages, conversation, tools=None):
    to_delete = []
    for message in ephemeral_messages:
        if tools is None or message["tool"] in tools:
            idx = message["idx"]
            conversation[idx]["content"] = message["replacement"]
            to_delete.append(message)
    for message in to_delete:
        ephemeral_messages.remove(message)


def generate_database_report(database_index, model, max_page_interval=20, max_pages_length=15000, output_dir=""):
    nb_documents = len(database_index)

    # Build summaries string
    documents_summaries = []
    for entry in database_index:
        documents_summaries.append({"name": entry["name"], "summary": entry["summary"]})
    documents_summaries = f"{documents_summaries}"
    summaries_length = count_tokens(model=model, message=documents_summaries)

    page_index_reports = []

    # Process each document
    for entry in tqdm.tqdm(database_index, desc="Documents"):
        infos = {
            "name": entry["name"],
            "errors": [],
            "warnings": []
        }

        # 🚨 Case: page index failed
        if entry["summary"] == "An error happened !":
            infos["errors"].append("Page Index not generated")
            infos["details"] = entry["page_index"]
            page_index_reports.append(infos)
            continue

        page_index = ast.literal_eval(entry["page_index"])
        if not isinstance(page_index, list):
            infos["errors"].append("Page index not valid !")
            infos["details"] = f"Page index = {entry['page_index']}"
            page_index_reports.append(infos)
            continue

        for i, section in enumerate(page_index):
            page_interval = section["pages"]

            # ❌ Invalid format
            if not re.match(r"^\s*\d+\s*-\s*\d+\s*$", page_interval):
                infos["errors"].append(f"Section {i+1} - Invalid page format: {page_interval}")
                continue

            # ✅ Extract numbers
            match = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", page_interval)
            n1 = int(match.group(1))
            n2 = int(match.group(2))

            # ❌ Logical error
            if n1 > n2:
                infos["errors"].append(f"Section {i+1} - Start page > end page ({n1}-{n2})")
                continue

            # Get content — uses the multidoc-compatible get_pages (path, not pdf_path)
            pages_content = get_pages(path=entry["path"], start=n1, end=n2, limit=9999999)

            nb_pages = n2 - n1 + 1
            pages_content_length = count_tokens(model=model, message=pages_content)

            # ⚠️ Interval warning
            if nb_pages > max_page_interval:
                infos["warnings"].append(
                    f"Section {i+1} - Too many pages ({nb_pages})"
                )

            # ⚠️ Token warning
            if pages_content_length > max_pages_length:
                infos["warnings"].append(
                    f"Section {i+1} - Too many tokens ({pages_content_length})"
                )

        page_index_reports.append(infos)

    # =========================
    # 📝 BUILD MARKDOWN REPORT
    # =========================

    report = "# 📊 Database Report\n\n"
    report += f"**Number of documents:** {nb_documents}\n\n"
    report += f"**Summaries token length:** {summaries_length}\n\n"
    report += "---\n\n"
    report += "Searching for:\n"
    report += "* LLM error during PageIndex generation (wrong format, infinite loop, ...)\n"
    report += "* Wrong format for PageIndex\n"
    report += "* Sections too large (too many pages and|or too many tokens)\n"

    for doc in page_index_reports:
        report += f"## 📄 {doc['name']}\n\n"

        # Errors
        if doc.get("errors"):
            report += "### ❌ Errors\n"
            for err in doc["errors"]:
                report += f"- {err}\n"
            report += "\n"

        # Warnings
        if doc.get("warnings"):
            report += "### ⚠️ Warnings\n"
            for warn in doc["warnings"]:
                report += f"- {warn}\n"
            report += "\n"

        # Details (optional)
        if doc.get("details"):
            report += "### 🧾 Details\n"
            report += f"```\n{doc['details']}\n```\n\n"

        if not doc.get("errors") and not doc.get("warnings"):
            report += "✅ No issues detected\n\n"

        report += "---\n\n"

    # =========================
    # 💾 SAVE FILE (optional)
    # =========================

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, "database_report.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(report)

    return report


prompts = {
    "find_start_of_document": """# Contexte
Voici les 15 premières pages d'un document. J'ai besoin de 2 choses :

- S'il y a une Table of Contents, je veux les numéros des images qui en contiennent un morceau.
- Si parmi ces 15 pages, le vrai contenu du document démarre (après la page de garde, les auteurs, les remerciements, etc...), je veux le numéro de l'image où le document démarre.


# Format de réponse
```json
{
	"Table_of_Contents": [x, y, z],
	"Start_of_Document": N
}
```

Si tu n'as pas la réponse, mets une liste vide [] pour table of contents, et "NA" pour start of document.""",


    "generate_TOC": """# Contexte
Tu reçois des images de pages d'un document. Ton objectif est d'identifier uniquement les headers (titres de sections) visibles sur chaque page.

# Définition stricte
Un "header" est un titre structurant le document (section ou sous-section), généralement mis en évidence visuellement.

# Ne sont PAS des headers
- Les définitions, exemples ou notes
- Le texte inline (même en gras ou en majuscules)
- Les légendes, tableaux ou annotations

# Critères pour identifier un header
Un header doit vérifier plusieurs des propriétés suivantes :
- Être visuellement distinct (taille de police plus grande, gras, espacement)
- Être isolé sur une ligne ou en début de section
- Structurer clairement le document (introduction d'une nouvelle partie)

Si tu hésites → IGNORE.

# Instructions
- Pour chaque image, liste uniquement les headers présents
- Recopie les headers EXACTEMENT comme ils apparaissent (ne pas reformuler)
- Une image peut ne contenir aucun header

# Format STRICT de sortie

Image X
- <header exact>
- <header exact>

Si aucun header :
Image X
- Aucun header""",


    # {TEXT}
    "clear_TOC": """# Context
You receive a list of pages containing automatically extracted elements that resemble titles. These elements may be noisy and redundant.

Your goal is to build a **clear, logical, and usable table of contents** for the document.

# Instructions
1. Identify every meaningful topic change, even minor ones.
2. Create sections that reflect the document's outline
3. Each section must span AT MOST 15 pages. Never exceed this limit.
4. Use the extracted titles as hints, but write clean and explicit section names.
5. You must create sub-section if a section is too long (more than 15 pages).
The goal is a readable and practical table of contents for searching the document.

# Output Format (STRICT)
Each header on its own line, with the page where the section begins (only 1 number):  

<header> - <page>  
<header> - <page>  
...

# Data
{TEXT}""",


    # {TEXT}
    "clear_TOC_og": """# Contexte
Voici une extraction page à page d'informations structurelles issues d'un document. L'objectif est de reconstruire la table des matières.

Règles pour les headers répétés :
- Si un header apparaît sur plusieurs pages **consécutives**, ne garder que la première occurrence.
- Si un header apparaît sur des pages **non consécutives**, garder chaque occurrence.

Ignore tout autre artéfact ou information non structurante.


# Format à respecter
Produis une table des matières sous la forme suivante, où Header est la numérotation du header avec son texte, et X est le numéro de page :

** Table des matières**
Header - X
Header - X
etc...


# Extraction page à page
{TEXT}""",


    # $TEXT$
    "toc_to_json": """# Contexte
Voici une table des matières d'un document. Réécris-là dans le format structuré suivant :

```json
[
{{
	"header": "...",
	"level_identifiable": "Oui" ou "Non",
	"level": "...",
	"page": "..."
}}
]
```

Tu devras ajouter l'information "level" pour chacun de ces headers. Le "level" correspond au niveau de hiérarchie du header.
Un "level" est identifiable si le header est accompagné d'une numérotation, comme par exemple "1.1" (level vaut 2) ou "1.3.1" (level vaut 3).
Si le "level" n'est pas identifiable, note 1. 



# Table des matières
{TEXT}""",



    # {TEXT}
    "short_summary_og": """# Contexte
Tu vas recevoir la table des matières d'un document, ainsi que la page de garde. Génère une **note très concise et directe** décrivant le **sujet** et ce que l'on peut trouver dans ce document. 
L'objectif est que, en lisant cette note, on puisse rapidement savoir si ce document contient les informations recherchées.


# Instructions :
- Résume le sujet et le contenu.
- N'utilise pas plus de 3 phrases.
- Utilise des mots-clés pertinents et séparés par des virgules.
- N'ajoute pas d'opinion, commentaire ou phrase explicative.


# Extrait du document {NAME}
{TEXT}""",


    # {TEXT}
    "short_summary": """# Contexte
Tu vas recevoir la table des matières d'un document, ainsi que la page de garde. Génère un résumé décrivant le **sujet** et ce que l'on peut trouver dans ce document. 
L'objectif est que, en lisant ce résumé, on puisse rapidement savoir si ce document contient les informations recherchées.


# Instructions :
- Résume le sujet et le contenu.
- N'utilise pas plus de 5 phrases, avec des mot-clés pertinents.
- N'ajoute pas d'opinion, commentaire ou phrase explicative.


# Extrait du document {NAME}
{TEXT}""",



    # {PAGE_INDEX}
    # {QUESTION}
    "search_agent": """# Contexte
Tu es un assistant avec accès à deux outils :
1. Un outil pour sélectionner un document
2. Un outil pour parcourir les pages d'un document sélectionné

Tu disposes d'un ensemble de documents, chacun décrit par un résumé.


# Règles
- Tu n'as PAS le droit d'inventer ou de deviner.
- Tu n'as PAS le droit de conclure que la réponse n'existe pas **sans** avoir lu de pages pertinentes avec l'outil.
- Tu peux utiliser les outils autant que tu veux jusqu'à avoir suffisamment d'informations.

---

# Comportement attendu
## Étape 1 — Sélection du document
- Si la question concerne les documents → tu DOIS d'abord sélectionner un document
- Choisis le document le plus pertinent en te basant sur les résumés fournis
- Tu ne peux pas appeler `get_pages` sans avoir sélectionné un document

## Étape 2 — Lecture des pages
- Une fois le document sélectionné → tu peux appeler `get_pages`

---

# Utilisation d'un outil
## Outil 1 - Sélection d'un document
Réponds avec

```tool
select_document(<document_name>)
```

puis attend le résultat avant de continuer tout réflexion ou rédaction de réponse. 
Tu vas recevoir un plan du document, te permettant de cibler les pages qui t'intéressent.


## Outil 2 - Lecture de pages
Réponds avec

```tool
get_pages(<page_debut>, <page_fin>)
```

puis attend le résultat avant de continuer toute réflexion ou rédaction de réponse.

---

# Arrêt
Lorsque tu as suffisamment d'informations pour répondre :
- Tu dois répondre directement à la question
- Tu ne dois PAS appeler l'outil
- Ta réponse doit être complète et précise

Format de réponse final :
```final
<ta réponse ici>
```

---

# Documents disponibles
{DOCUMENTS_SUMMARIES}


# Question
{QUESTION}"""
}
