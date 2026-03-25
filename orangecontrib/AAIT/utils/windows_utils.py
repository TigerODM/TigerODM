# Copier-colle qui utilise la fonction de Windows (pour avoir la fenêtre classique qui s'ouvre)

import os
import threading
import time
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\","/"):
    from Orange.widgets.orangecontrib.AAIT.utils import SimpleDialogQt
else:
    from orangecontrib.AAIT.utils import SimpleDialogQt
if os.name=='nt':
    import os.path

    from win32com.shell import shell, shellcon
    import ctypes
    import ctypes.wintypes
    from ctypes import windll, c_wchar_p
    import ctypes.wintypes as wt


    def win32_shellcopy(src, dest):
        """
        Copy files and directories using Windows shell.

        :param src: Path or a list of paths to copy. Filename portion of a path
                    (but not directory portion) can contain wildcards ``*`` and
                    ``?``.
        :param dst: destination directory.
        :returns: ``True`` if the operation completed successfully,
                  ``False`` if it was aborted by user (completed partially).
        :raises: ``WindowsError`` if anything went wrong. Typically, when source
                 file was not found.

        .. seealso:
            `SHFileperation on MSDN <http://msdn.microsoft.com/en-us/library/windows/desktop/bb762164(v=vs.85).aspx>`
        """
        if not os.path.exists(src):
            SimpleDialogQt.BoxError("Error file not exist : "+src)
            return
        if isinstance(src, str):
            src = os.path.abspath(src)
        else:  # iterable
            src = '\0'.join(os.path.abspath(path) for path in src)

        result, aborted = shell.SHFileOperation((
            0,
            shellcon.FO_COPY,
            src,
            os.path.abspath(dest),
            shellcon.FOF_NOCONFIRMMKDIR,  # flags
            None,
            None))

        if not aborted and result != 0:
            # Note: raising a WindowsError with correct error code is quite
            # difficult due to SHFileOperation historical idiosyncrasies.
            # Therefore we simply pass a message.
            raise WindowsError('SHFileOperation failed: 0x%08x' % result)

        return not aborted


    def select_folder_ctypes(title="Select a directory"):
        """
        Ouvre une boîte de sélection de dossier Windows toujours au premier plan
        (devant toutes les fenêtres du système), sans threads ni repop.
        """

        BIF_RETURNONLYFSDIRS = 0x0001
        BIF_NEWDIALOGSTYLE = 0x0040
        MAX_PATH = 32767

        BFFM_INITIALIZED = 1
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040
        HWND_TOPMOST = -1

        SW_SHOW = 5

        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        ole32 = ctypes.windll.ole32

        class BROWSEINFO(ctypes.Structure):
            _fields_ = [
                ("hwndOwner", wt.HWND),
                ("pidlRoot", ctypes.c_void_p),
                ("pszDisplayName", ctypes.c_wchar_p),
                ("lpszTitle", ctypes.c_wchar_p),
                ("ulFlags", wt.UINT),
                ("lpfn", ctypes.c_void_p),
                ("lParam", ctypes.c_void_p),
                ("iImage", wt.INT),
            ]

        BFFCALLBACK = ctypes.WINFUNCTYPE(wt.INT, wt.HWND, wt.UINT, wt.LPARAM, wt.LPARAM)

        SHBrowseForFolderW = shell32.SHBrowseForFolderW
        SHGetPathFromIDListW = shell32.SHGetPathFromIDListW
        CoTaskMemFree = ole32.CoTaskMemFree
        CoInitializeEx = ole32.CoInitializeEx
        CoUninitialize = ole32.CoUninitialize

        SHBrowseForFolderW.argtypes = [ctypes.POINTER(BROWSEINFO)]
        SHBrowseForFolderW.restype = ctypes.c_void_p
        SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        SHGetPathFromIDListW.restype = wt.BOOL

        def _cb(hwnd, uMsg, lParam, lpData):
            if uMsg == BFFM_INITIALIZED:
                # Force la fenêtre au tout premier plan
                user32.ShowWindow(hwnd, SW_SHOW)
                user32.SetForegroundWindow(hwnd)
                user32.SetActiveWindow(hwnd)
                user32.BringWindowToTop(hwnd)
                user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                    SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
            return 0

        cb = BFFCALLBACK(_cb)

        COINIT_APARTMENTTHREADED = 0x2
        CoInitializeEx(None, COINIT_APARTMENTTHREADED)

        display_name_buffer = ctypes.create_unicode_buffer(MAX_PATH)
        bi = BROWSEINFO()
        bi.hwndOwner = 0  # pas d’attachement à une autre fenêtre
        bi.pidlRoot = None
        bi.pszDisplayName = ctypes.cast(display_name_buffer, ctypes.c_wchar_p)
        bi.lpszTitle = title
        bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE
        bi.lpfn = ctypes.cast(cb, ctypes.c_void_p)
        bi.lParam = None
        bi.iImage = 0

        pidl = SHBrowseForFolderW(ctypes.byref(bi))

        folder_path = ""
        if pidl:
            out_buf = ctypes.create_unicode_buffer(MAX_PATH)
            if SHGetPathFromIDListW(pidl, out_buf):
                folder_path = out_buf.value
            CoTaskMemFree(ctypes.c_void_p(pidl))

        CoUninitialize()
        if not folder_path:
            return ""

        folder_path = folder_path.replace("\\", "/")

        if len(folder_path) > 1 and not folder_path.endswith("/"):
            folder_path += "/"

        return folder_path


    # Sélectionner un fichier image unique
    # path = select_file_ctypes(multi_select=False, file_filter="Images (*.jpg;*.png;*.jpeg)")
    #
    # # Sélectionner plusieurs fichiers Word
    # paths = select_file_ctypes(multi_select=True, file_filter="Word Documents (*.docx;*.doc)")
    import ctypes
    import ctypes.wintypes

    # --- Déclarer UNE SEULE FOIS au niveau module (pas dans la fonction) ---
    user32 = ctypes.windll.user32
    comdlg32 = ctypes.windll.comdlg32

    EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    # Définir la signature de EnumWindows UNE SEULE FOIS
    user32.EnumWindows.argtypes = (EnumWindowsProc, wt.LPARAM)
    user32.EnumWindows.restype = wt.BOOL


    def select_file_ctypes(multi_select=False, file_filter="All Files (*.*)", dialog_title="Select File(s)"):
        OFN_ALLOWMULTISELECT = 0x00000200
        OFN_EXPLORER = 0x00080000
        OFN_FILEMUSTEXIST = 0x00001000
        MAX_PATH = 65536

        class OPENFILENAME(ctypes.Structure):
            _fields_ = [
                ("lStructSize", wt.DWORD),
                ("hwndOwner", wt.HWND),
                ("hInstance", wt.HINSTANCE),
                ("lpstrFilter", ctypes.c_wchar_p),
                ("lpstrCustomFilter", ctypes.c_wchar_p),
                ("nMaxCustFilter", wt.DWORD),
                ("nFilterIndex", wt.DWORD),
                ("lpstrFile", ctypes.c_wchar_p),
                ("nMaxFile", wt.DWORD),
                ("lpstrFileTitle", ctypes.c_wchar_p),
                ("nMaxFileTitle", wt.DWORD),
                ("lpstrInitialDir", ctypes.c_wchar_p),
                ("lpstrTitle", ctypes.c_wchar_p),
                ("Flags", wt.DWORD),
                ("nFileOffset", wt.WORD),
                ("nFileExtension", wt.WORD),
                ("lpstrDefExt", ctypes.c_wchar_p),
                ("lCustData", wt.LPARAM),
                ("lpfnHook", ctypes.c_void_p),
                ("lpTemplateName", ctypes.c_wchar_p),
                ("pvReserved", ctypes.c_void_p),
                ("dwReserved", wt.DWORD),
                ("FlagsEx", wt.DWORD),
            ]

        # Filter string Windows: \0 séparateurs + double \0 final
        if "(" in file_filter and ")" in file_filter:
            description = file_filter.split("(")[0].strip()
            pattern = file_filter[file_filter.find("(") + 1:file_filter.find(")")]
        else:
            description = "All Files"
            pattern = "*.*"
        filter_combined = f"{description}\0{pattern}\0All Files\0*.*\0\0"

        file_buffer = ctypes.create_unicode_buffer(MAX_PATH)

        ofn = OPENFILENAME()
        ofn.lStructSize = ctypes.sizeof(OPENFILENAME)
        ofn.hwndOwner = 0
        ofn.lpstrFilter = filter_combined
        ofn.lpstrFile = ctypes.cast(file_buffer, ctypes.c_wchar_p)
        ofn.nMaxFile = MAX_PATH
        ofn.lpstrTitle = dialog_title
        ofn.Flags = OFN_EXPLORER | OFN_FILEMUSTEXIST
        if multi_select:
            ofn.Flags |= OFN_ALLOWMULTISELECT

        # --- Avant ouverture : liste des HWND ---
        hwnd_list_before = []

        def _enum_before(hwnd, lParam):
            hwnd_list_before.append(hwnd)
            return True

        cb_before = EnumWindowsProc(_enum_before)  # garder une référence !
        user32.EnumWindows(cb_before, 0)

        # --- Ouvre la boîte ---
        if not comdlg32.GetOpenFileNameW(ctypes.byref(ofn)):
            return ""

        time.sleep(0.1)

        # --- Après ouverture : liste des HWND ---
        hwnd_list_after = []

        def _enum_after(hwnd, lParam):
            hwnd_list_after.append(hwnd)
            return True

        cb_after = EnumWindowsProc(_enum_after)  # garder une référence !
        user32.EnumWindows(cb_after, 0)

        # peut etre a remettre (pyflakes warning)
        #new_hwnds = list(set(hwnd_list_after) - set(hwnd_list_before))

        # ... le reste de ton code (détection de la fenêtre, thread enforce_modal, parsing buffer) ...
        buffer_content = ctypes.wstring_at(ctypes.addressof(file_buffer), file_buffer._length_)
        parts = [p.replace("\\", "/") for p in buffer_content.split("\0") if p]

        if multi_select:
            if len(parts) >= 2:
                folder = parts[0]
                files = parts[1:]
                return "//////".join([f"{folder}/{f}" for f in files])
            return parts[0] if parts else ""
        else:
            return parts[0] if parts else ""




    def select_new_file_ctypes(file_filter="All Files (*.*)", dialog_title="Create New File"):
        """
        Opens a native Windows file dialog for creating a new file.

        Args:
            file_filter (str): File type filters, e.g., "Text Files (*.txt)" or "All Files (*.*)".

        Returns:
            str: Selected file path as a string, or an empty string if cancelled.
        """
        OFN_EXPLORER = 0x00080000
        MAX_PATH = 65536  # Large buffer for filename

        class OPENFILENAME(ctypes.Structure):
            _fields_ = [
                ("lStructSize", ctypes.wintypes.DWORD),
                ("hwndOwner", ctypes.wintypes.HWND),
                ("hInstance", ctypes.wintypes.HINSTANCE),
                ("lpstrFilter", ctypes.c_wchar_p),
                ("lpstrCustomFilter", ctypes.c_wchar_p),
                ("nMaxCustFilter", ctypes.wintypes.DWORD),
                ("nFilterIndex", ctypes.wintypes.DWORD),
                ("lpstrFile", ctypes.c_wchar_p),
                ("nMaxFile", ctypes.wintypes.DWORD),
                ("lpstrFileTitle", ctypes.c_wchar_p),
                ("nMaxFileTitle", ctypes.wintypes.DWORD),
                ("lpstrInitialDir", ctypes.c_wchar_p),
                ("lpstrTitle", ctypes.c_wchar_p),
                ("Flags", ctypes.wintypes.DWORD),
                ("nFileOffset", ctypes.wintypes.WORD),
                ("nFileExtension", ctypes.wintypes.WORD),
                ("lpstrDefExt", ctypes.c_wchar_p),
                ("lCustData", ctypes.wintypes.LPARAM),
                ("lpfnHook", ctypes.c_void_p),
                ("lpTemplateName", ctypes.c_wchar_p),
                ("pvReserved", ctypes.c_void_p),
                ("dwReserved", ctypes.wintypes.DWORD),
                ("FlagsEx", ctypes.wintypes.DWORD),
            ]

        user32 = ctypes.windll.user32
        comdlg32 = ctypes.windll.comdlg32

        # Convert file_filter into Windows format: "Description\0Pattern\0..."
        if "(" in file_filter and ")" in file_filter:
            description = file_filter.split("(")[0].strip()
            pattern = file_filter[file_filter.find("(")+1:file_filter.find(")")]
        else:
            description = "All Files"
            pattern = "*.*"

        # Extract first extension for default
        first_ext = pattern.split(";")[0].strip().lstrip("*.")
        if not first_ext:
            first_ext = "txt"

        filter_combined = f"{description}\0{pattern}\0All Files\0*.*\0\0"

        file_buffer = ctypes.create_unicode_buffer(MAX_PATH)

        ofn = OPENFILENAME()
        ofn.lStructSize = ctypes.sizeof(OPENFILENAME)
        ofn.hwndOwner = 0
        ofn.lpstrFilter = filter_combined
        ofn.lpstrFile = ctypes.cast(file_buffer, ctypes.c_wchar_p)
        ofn.nMaxFile = MAX_PATH
        ofn.lpstrTitle = dialog_title
        ofn.Flags = OFN_EXPLORER
        ofn.lpstrDefExt = first_ext  # <- extension ajoutée automatiquement si absente

        # Mémoriser les fenêtres existantes
        hwnd_list_before = []
        def enum_windows_proc(hwnd, lParam):
            hwnd_list_before.append(hwnd)
            return True

        EnumWindows = user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        EnumWindows(EnumWindowsProc(enum_windows_proc), 0)

        # Ouvre la boîte de dialogue
        if not comdlg32.GetSaveFileNameW(ctypes.byref(ofn)):
            return ""

        time.sleep(0.1)

        # Fenêtres après
        hwnd_list_after = []
        EnumWindows(EnumWindowsProc(lambda hwnd, lParam: hwnd_list_after.append(hwnd) or True), 0)
        new_hwnds = list(set(hwnd_list_after) - set(hwnd_list_before))

        selector_hwnd = None
        target_phrase = (dialog_title or "Save").lower()
        for hwnd in new_hwnds:
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                window_title = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, window_title, length + 1)
                if target_phrase in window_title.value.lower():
                    selector_hwnd = hwnd
                    break

        def enforce_modal(hwnd):
            if not hwnd:
                return
            while user32.IsWindow(hwnd):
                user32.SetForegroundWindow(hwnd)
                user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0,
                                    0x0002 | 0x0001 | 0x0040)  # SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
                time.sleep(0.2)

        if selector_hwnd:
            threading.Thread(target=enforce_modal, args=(selector_hwnd,), daemon=True).start()

        result = ctypes.wstring_at(ctypes.addressof(file_buffer), file_buffer._length_)
        return result.split('\0', 1)[0].replace("\\", "/")


    def BoxMessage(text: str, mode: int = 0, title: str = None) -> int:
        """
        Affiche une boîte native Windows (via ctypes).
        mode = 0 -> Error
        mode = 1 -> Warning
        mode = 2 -> Info
        Retourne l'ID du bouton cliqué (IDOK = 1).
        usage     BoxMessage("Ceci est une erreur", 0)
        BoxMessage("Ceci est un avertissement", 1)
        BoxMessage("Ceci est une information", 2)
        BoxMessage("Ceci est une erreur", 0,"titr1")
        BoxMessage("Ceci est un avertissement", 1,"titr2")
        BoxMessage("Ceci est une information", 2,"titr3")


        """


        # Flags boutons
        MB_OK = 0x00000000
        MB_SYSTEMMODAL   = 0x00001000
        MB_SETFOREGROUND = 0x00010000
        MB_TOPMOST       = 0x00040000

        # Icônes selon mode
        if mode == 0:  # Error
            icon_flag = 0x00000010  # MB_ICONERROR
            if title is None: title = "Error"
        elif mode == 1:  # Warning
            icon_flag = 0x00000030  # MB_ICONWARNING
            if title is None: title = "Warning"
        elif mode == 2:  # Info
            icon_flag = 0x00000040  # MB_ICONINFORMATION
            if title is None: title = "Information"
        else:
            raise ValueError("mode doit être 0=Error, 1=Warning, 2=Info")

        flags = MB_OK | icon_flag | MB_SYSTEMMODAL | MB_SETFOREGROUND | MB_TOPMOST

        return windll.user32.MessageBoxW(0, c_wchar_p(text), c_wchar_p(title), flags)

