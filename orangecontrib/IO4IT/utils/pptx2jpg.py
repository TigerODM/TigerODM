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
            except: pass
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
            presentation.SaveAs(str(pdf_path), 32) # 32 = ppSaveAsPDF
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
    return src.with_suffix(".pdf")

def process_one_pptx(file_path_str: str, unique_folder: bool = True):
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return [file_path_str, "", "nok", "0.0", "Erreur: PyMuPDF non installé"]

    t0 = time.time()
    src = Path(file_path_str).resolve()
    out_dir = src.parent / (f"images_{src.stem}" if unique_folder else "images")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    method = get_conversion_method()
    img_list = []

    try:
        # --- PHASE 1: GENERATE IMAGES ---
        if method == "aspose":
        #    import aspose.slides as slides
        #    with slides.Presentation(str(src)) as pres:
        #        for i, slide in enumerate(pres.slides, start=1):
        #            img_path = out_dir / f"{src.stem}_slide_{i:03d}.jpg"
        #            slide.get_thumbnail(1.5, 1.5).save(str(img_path), slides.export.ImageFormat.JPEG)
        #            img_list.append(str(img_path))
            print("converting slides without having libre office or office isn't possible for the moment")
        else:
            # Office or LibreOffice both generate a PDF first
            pdf_path = out_dir / f"{src.stem}.pdf"
            if method == "office":
                convert_via_office(src, pdf_path)
            else: # libreoffice
                convert_via_libreoffice(src, out_dir)
            
            # Convert PDF pages to JPG using PyMuPDF
            doc = fitz.open(str(pdf_path))
            for i, page in enumerate(doc, start=1):
                pix = page.get_pixmap(dpi=150)
                img_path = out_dir / f"{src.stem}_slide_{i:03d}.jpg"
                pix.save(str(img_path))
                img_list.append(str(img_path))
            doc.close()
            if pdf_path.exists(): pdf_path.unlink()

        duration = time.time() - t0
        return [str(src), "|".join(img_list), "ok", f"{duration:.2f}", f"{len(img_list)} slides ({method})"]

    except Exception as e:
        return [str(src), "", "nok", f"{time.time()-t0:.2f}", f"Method {method} failed: {str(e)}"]