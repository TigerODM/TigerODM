import sys
import time
import subprocess
from pathlib import Path

def pptx_to_pdf(pptx_path: Path) -> Path:
    pdf_path = pptx_path.with_suffix(".pdf")
    if sys.platform.startswith("win"):
        import win32com.client
        powerpoint = win32com.client.Dispatch("PowerPoint.Application")
        try:
            presentation = powerpoint.Presentations.Open(str(pptx_path), WithWindow=False)
            presentation.SaveAs(str(pdf_path), 32)
            presentation.Close()
        except Exception as e:
            raise RuntimeError(f"Erreur PowerPoint : {e}")
    elif sys.platform == "darwin":
        script = f'tell application "Microsoft PowerPoint" to save (open POSIX file "{pptx_path}") in POSIX file "{pdf_path}" as PDF'
        subprocess.run(["osascript", "-e", script], check=True)
    else:
        raise RuntimeError("Système d'exploitation non supporté.")
    return pdf_path

def process_one_pptx(file_path_str: str, unique_folder: bool = True):
    try:
        import fitz
    except ImportError:
        return [file_path_str, "", "nok", "0.0", "Erreur: PyMuPDF (fitz) non installé"]

    t0 = time.time()
    src = Path(file_path_str).resolve()

    # ✅ unique_folder=True  → un dossier par pptx : images_monFichier/
    # ✅ unique_folder=False → tout dans un dossier commun : images/ (à côté des pptx)
    if unique_folder:
        out_dir = src.parent / f"images_{src.stem}"
    else:
        out_dir = src.parent / "images"

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        
        pdf_path = pptx_to_pdf(src)
        
        doc = fitz.open(str(pdf_path))
        img_list = []
        for i, page in enumerate(doc, start=1):
            pix = page.get_pixmap(dpi=150)
            # ✅ Préfixe avec le nom du pptx pour éviter les collisions en mode commun
            img_path = out_dir / f"{src.stem}_slide_{i:03d}.jpg"
            pix.save(str(img_path))
            img_list.append(str(img_path))
        doc.close()
        
        if pdf_path.exists():
            pdf_path.unlink()
        
        duration = time.time() - t0
        return [str(src), "|".join(img_list), "ok", f"{duration:.2f}", f"{len(img_list)} slides"]
    
    except Exception as e:
        duration = time.time() - t0
        import traceback
        return [str(src), "", "nok", f"{duration:.2f}", f"{str(e)}\n{traceback.format_exc()}"]