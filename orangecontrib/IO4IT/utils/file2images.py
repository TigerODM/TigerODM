import sys
import time
import subprocess
import shutil
from pathlib import Path


def get_conversion_method():
    """Determines the best available conversion method."""
    # 1. Check for MS Office
    if sys.platform.startswith("win"):
        try:
            import win32com.client
            # Try to see if the COM object is registered
            win32com.client.GetActiveObject("PowerPoint.Application")
            return "office"
        except:
            try:
                # If not running, try to see if it's dispatchable
                win32com.client.Dispatch("PowerPoint.Application")
                return "office"
            except:
                pass
    elif sys.platform == "darwin":
        # Check if PowerPoint app exists on Mac
        if Path("/Applications/Microsoft PowerPoint.app").exists():
            return "office"

    # 2. Check for LibreOffice (soffice)
    if shutil.which("soffice"):
        return "libreoffice"

    # 3. Fallback to Aspose
    return "aspose"


def convert_via_office(src: Path, pdf_path: Path):
    if sys.platform.startswith("win"):
        import win32com.client
        powerpoint = win32com.client.Dispatch("PowerPoint.Application")
        try:
            presentation = powerpoint.Presentations.Open(str(src), WithWindow=False)
            presentation.SaveAs(str(pdf_path), 32)  # 32 = ppSaveAsPDF
            presentation.Close()
        finally:
            # Note: We don't quit() powerpoint here to avoid killing other open docs
            pass
    elif sys.platform == "darwin":
        script = f'tell application "Microsoft PowerPoint" to save (open POSIX file "{src}") in POSIX file "{pdf_path}" as PDF'
        subprocess.run(["osascript", "-e", script], check=True)


def convert_via_libreoffice(src: Path, out_dir: Path):
    subprocess.run([
        "soffice", "--headless", "--convert-to", "pdf",
        "--outdir", str(out_dir), str(src)
    ], check=True, capture_output=True)
    return out_dir / f"{src.stem}.pdf"


def parse_pages(spec, total):
    """Convertit une spécification de pages en liste d'indices 1-based, triés et dédupliqués.

    Exemples (total = nombre de pages du document) :
        None / "" / "all" / "*"  -> toutes les pages
        "1"                      -> [1]
        "1,3,5"                  -> [1, 3, 5]
        "1-3"                    -> [1, 2, 3]
        "2-4,6"                  -> [2, 3, 4, 6]
    Les pages hors intervalle [1, total] sont ignorées silencieusement.
    """
    if spec is None:
        return list(range(1, total + 1))

    spec = str(spec).strip().lower()
    if spec in ("", "all", "toutes", "tout", "*"):
        return list(range(1, total + 1))

    pages = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                a, b = int(a), int(b)
                for p in range(min(a, b), max(a, b) + 1):
                    pages.add(p)
            else:
                pages.add(int(part))
        except ValueError:
            # Fragment invalide (ex. "abc") -> on l'ignore
            continue

    return sorted(p for p in pages if 1 <= p <= total)


# Formats gérés nativement par Pixmap.save() de PyMuPDF.
# Les autres (tif/tiff, webp, bmp...) passent par Pillow via pix.pil_save().
_NATIVE_FORMATS = {"jpg", "jpeg", "png", "pnm", "pgm", "ppm", "pbm", "pam", "tga", "ps", "psd"}


def normalize_ext(out_ext):
    """Nettoie l'extension demandée : minuscule, sans point initial, jpg par défaut."""
    ext = str(out_ext or "jpg").strip().lower().lstrip(".")
    if ext == "jpeg":
        ext = "jpg"
    return ext or "jpg"


def normalize_dpi(dpi, default=150):
    """Convertit le DPI en entier valide (> 0), sinon retombe sur `default`."""
    try:
        dpi = int(dpi)
    except (TypeError, ValueError):
        return default
    return dpi if dpi > 0 else default


def _save_pixmap(pix, img_path: Path, ext: str):
    """Sauvegarde le pixmap au bon format selon l'extension."""
    if ext in _NATIVE_FORMATS:
        pix.save(str(img_path))
    else:
        # tif/tiff et autres formats -> nécessite Pillow
        pix.pil_save(str(img_path))


def process_one_file(file_path_str: str, out_dir_str: str = None,
                     pages: str = "all", out_ext: str = "jpg",
                     dpi: int = 150, unique_folder: bool = True):
    """Convertit un PPTX (ou PDF) en images.

    Args:
        file_path_str : chemin du fichier source (.pptx ou .pdf).
        out_dir_str   : dossier de sortie. Si None/vide, on retombe sur le
                        comportement historique (images_<nom> ou images/).
        pages         : pages/slides à extraire ("all", "1", "1,3", "1-3"...).
        out_ext       : format d'image de sortie ("jpg", "png", "tif"...).
        dpi           : résolution de rendu en points par pouce (défaut 150).
        unique_folder : utilisé seulement quand out_dir_str n'est pas fourni.

    Retour : [src, "img1|img2|...", "ok"/"nok", durée, message]
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return [file_path_str, "", "nok", "0.0", "Erreur: PyMuPDF non installé"]

    t0 = time.time()
    src = Path(file_path_str).resolve()
    ext_out = normalize_ext(out_ext)
    dpi_out = normalize_dpi(dpi)

    # --- Dossier de sortie : colonne prioritaire, sinon fallback historique ---
    if out_dir_str and str(out_dir_str).strip():
        out_dir = Path(str(out_dir_str).strip())
    else:
        out_dir = src.parent / (f"images_{src.stem}" if unique_folder else "images")
    out_dir.mkdir(parents=True, exist_ok=True)

    img_list = []
    ext = src.suffix.lower()
    method = "pdf"          # méthode par défaut si l'entrée est déjà un PDF
    temp_pdf = False        # True si on a généré un PDF intermédiaire à supprimer

    try:
        # --- PHASE 1 : obtenir un PDF ---
        if ext == ".pdf":
            pdf_path = src
        else:
            method = get_conversion_method()
            if method == "aspose":
                # import aspose.slides as slides  # (fallback désactivé)
                return [str(src), "", "nok", f"{time.time()-t0:.2f}",
                        "Conversion impossible sans LibreOffice ou MS Office"]

            pdf_path = out_dir / f"{src.stem}.pdf"
            temp_pdf = True
            if method == "office":
                convert_via_office(src, pdf_path)
            else:  # libreoffice
                convert_via_libreoffice(src, out_dir)

        # --- PHASE 2 : rasteriser uniquement les pages demandées ---
        doc = fitz.open(str(pdf_path))
        wanted = parse_pages(pages, doc.page_count)

        for i in wanted:
            page = doc.load_page(i - 1)  # fitz est 0-based
            pix = page.get_pixmap(dpi=dpi_out)
            img_path = out_dir / f"{src.stem}_slide_{i:03d}.{ext_out}"
            _save_pixmap(pix, img_path, ext_out)
            img_list.append(str(img_path))
        doc.close()

        if temp_pdf and pdf_path.exists():
            pdf_path.unlink()

        duration = time.time() - t0
        if not img_list:
            return [str(src), "", "nok", f"{duration:.2f}",
                    f"Aucune page valide pour la spec '{pages}' ({method})"]

        return [str(src), "|".join(img_list), "ok", f"{duration:.2f}",
                f"{len(img_list)} image(s) .{ext_out} @ {dpi_out} DPI ({method})"]

    except Exception as e:
        return [str(src), "", "nok", f"{time.time()-t0:.2f}",
                f"Method {method} failed: {str(e)}"]
