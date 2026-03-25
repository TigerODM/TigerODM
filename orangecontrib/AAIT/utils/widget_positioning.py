from AnyQt.QtWidgets import QApplication
from AnyQt.QtCore import QTimer
import re
#allows displaying a widget on opening
# add (not sure!)
# save_position = False
# after class declaration
# call show_and_adjust_at_opening at the end of init
def show_and_adjust_at_opening(argself,str_position):
    # "left", "top-left", "bottom-left","bottom", "bottom-left", "bottom-right"
    str_position=str(str_position)
    if str_position=="None" or str_position=="none":
        return
    argself.show()
    QTimer.singleShot(1000, lambda: adjust_to_quarter(argself,str_position))

def _parse_variable_position(spec: str):
    """
    Attend: vXX_dvYY_hxx_dhyy
      vXX  = % de l'écran (Y du coin haut)
      dvYY = % de l'écran (hauteur)
      hxx  = % de l'écran (X du coin gauche)
      dhyy = % de l'écran (largeur)
    Retourne (v, dv, h, dh) en int si OK, sinon None.
    """
    if not isinstance(spec, str):
        return None

    m = re.fullmatch(r"v(\d{1,3})_dv(\d{1,3})_h(\d{1,3})_dh(\d{1,3})", spec.strip())
    if not m:
        return None

    v, dv, h, dh = map(int, m.groups())

    # bornes simples: 0..100
    if any(p < 0 or p > 100 for p in (v, dv, h, dh)):
        return None

    # éviter taille nulle (tu peux enlever si tu veux autoriser 0)
    if dv == 0 or dh == 0:
        return None

    # vérifier que le rectangle reste dans l'écran (en %)
    if v + dv > 100 or h + dh > 100:
        return None

    return v, dv, h, dh

def adjust_to_quarter(argself, position: str):
    """
    Resize and position the widget depending on a screen region:
    - left / right  → full height, half width
    - top / bottom  → full width, half height
    - corners       → quarter (half width × half height)
    """
    app = QApplication.instance()
    screen = app.primaryScreen().availableGeometry()

    sw, sh = screen.width(), screen.height()

    parsed = _parse_variable_position(position)
    if parsed is not None:
        v, dv, h, dh = parsed

        # conversion % -> pixels
        y = screen.y() + int(round(sh * (v / 100.0)))
        h_px = int(round(sh * (dv / 100.0)))

        x = screen.x() + int(round(sw * (h / 100.0)))
        w_px = int(round(sw * (dh / 100.0)))

        argself.resize(w_px, h_px)
        argself.move(x, y)
        return



    if position == "fullscreen":
        # full screen
        w, h = sw, sh
    # ---- CALCUL TAILLE ----
    elif position in ("left", "right"):
        # full height, half width
        w, h = sw // 2, sh

    elif position in ("top", "bottom"):
        # full width, half height
        w, h = sw, sh // 2

    elif position in ("top-left", "top-right", "bottom-left", "bottom-right"):
        # quarter (default case)
        w, h = sw // 2, sh // 2
    elif position == "none" or position == "None":
        return  # ou ne rien faire
    else:
        # fallback: centered
        w, h = sw // 2, sh // 2

    # ---- CALCUL POSITION ----
    if position in ("left", "top-left", "bottom-left"):
        x = screen.x()
    elif position in ("right", "top-right", "bottom-right"):
        x = screen.x() + sw - w
    else:
        x = screen.x() + (sw - w) // 2

    if position in ("top", "top-left", "top-right"):
        y = screen.y()
    elif position in ("bottom", "bottom-left", "bottom-right"):
        y = screen.y() + sh - h
    else:
        y = screen.y() + (sh - h) // 2

    # ---- APPLIQUER ----
    argself.resize(w, h)
    argself.move(x, y)

