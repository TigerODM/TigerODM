try:
    from PyQt5 import uic
    #print("uic imported from PyQt5")
except ImportError:
    print("This Orange does not run on PyQt5, could not import uic")
    try:
        from PyQt6 import uic
        #("uic imported from PyQt6")
    except ImportError:
        print("This Orange does not run on PyQt6, could not import uic")
_ = uic  # Supprime l'avertissement Pyflakes si uic n'est pas encore utilisé