import glob
import ctypes
import platform
from ctypes import wintypes


def has_gpu_with_min_vram(min_vram_gb=12):
    """
    Retourne True si au moins un GPU dispose d'au moins `min_vram_gb` Go.
    Sans appel en ligne de commande.
    En cas d'erreur : False.

    Plateformes gérées :
      - Windows : DXGI (VRAM dédiée)
      - macOS   : Metal (recommendedMaxWorkingSetSize)
      - Linux   : best effort via /sys et /proc
    """
    try:
        threshold_bytes = int(min_vram_gb * 1024 * 1024 * 1024)
        system = platform.system()

        if system == "Windows":
            return _has_gpu_windows_dxgi(threshold_bytes)
        elif system == "Darwin":
            return _has_gpu_macos_metal(threshold_bytes)
        elif system == "Linux":
            return _has_gpu_linux_best_effort(threshold_bytes)

        return False
    except Exception:
        return False


# ======================================================================
# WINDOWS : DXGI
# ======================================================================

def _has_gpu_windows_dxgi(threshold_bytes):
    try:
        # GUID de IDXGIFactory1 : {770aae78-f26f-4dba-a829-253c83d1b387}
        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_uint32),
                ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        IID_IDXGIFactory1 = GUID(
            0x770aae78,
            0xf26f,
            0x4dba,
            (ctypes.c_ubyte * 8)(0xa8, 0x29, 0x25, 0x3c, 0x83, 0xd1, 0xb3, 0x87),
        )

        class LUID(ctypes.Structure):
            _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

        class DXGI_ADAPTER_DESC1(ctypes.Structure):
            _fields_ = [
                ("Description", ctypes.c_wchar * 128),
                ("VendorId", ctypes.c_uint),
                ("DeviceId", ctypes.c_uint),
                ("SubSysId", ctypes.c_uint),
                ("Revision", ctypes.c_uint),
                ("DedicatedVideoMemory", ctypes.c_size_t),
                ("DedicatedSystemMemory", ctypes.c_size_t),
                ("SharedSystemMemory", ctypes.c_size_t),
                ("AdapterLuid", LUID),
                ("Flags", ctypes.c_uint),
            ]

        dxgi = ctypes.WinDLL("dxgi.dll")
        CreateDXGIFactory1 = dxgi.CreateDXGIFactory1
        CreateDXGIFactory1.argtypes = [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
        CreateDXGIFactory1.restype = ctypes.HRESULT

        factory = ctypes.c_void_p()
        hr = CreateDXGIFactory1(ctypes.byref(IID_IDXGIFactory1), ctypes.byref(factory))
        if hr != 0 or not factory.value:
            return False

        # VTable IDXGIFactory1
        factory_ptr = ctypes.cast(factory, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
        vtbl = factory_ptr.contents

        # Méthodes utiles :
        # 2 = Release
        # 12 = EnumAdapters1
        EnumAdapters1Proto = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)
        )
        ReleaseProto = ctypes.WINFUNCTYPE(ctypes.c_uint, ctypes.c_void_p)

        enum_adapters1 = EnumAdapters1Proto(vtbl[12])
        release_factory = ReleaseProto(vtbl[2])

        i = 0
        found = False

        while True:
            adapter = ctypes.c_void_p()
            hr = enum_adapters1(factory, i, ctypes.byref(adapter))
            if hr != 0 or not adapter.value:
                break

            try:
                adapter_ptr = ctypes.cast(adapter, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
                avtbl = adapter_ptr.contents

                # IDXGIAdapter1.GetDesc1 index 10, Release index 2
                GetDesc1Proto = ctypes.WINFUNCTYPE(
                    ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(DXGI_ADAPTER_DESC1)
                )
                release_adapter = ReleaseProto(avtbl[2])
                get_desc1 = GetDesc1Proto(avtbl[10])

                desc = DXGI_ADAPTER_DESC1()
                hr2 = get_desc1(adapter, ctypes.byref(desc))
                if hr2 == 0:
                    dedicated = int(desc.DedicatedVideoMemory or 0)
                    if dedicated >= threshold_bytes:
                        found = True
                        release_adapter(adapter)
                        break

                release_adapter(adapter)
            except Exception:
                try:
                    adapter_ptr = ctypes.cast(adapter, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
                    avtbl = adapter_ptr.contents
                    ReleaseProto(avtbl[2])(adapter)
                except Exception:
                    pass

            i += 1

        release_factory(factory)
        return found

    except Exception:
        return False


# ======================================================================
# MACOS : Metal via Objective-C runtime
# ======================================================================

def _has_gpu_macos_metal(threshold_bytes):
    """
    Sur macOS, il n'y a pas toujours de 'VRAM dédiée' au sens strict,
    surtout sur Apple Silicon (mémoire unifiée).
    On utilise `recommendedMaxWorkingSetSize` comme meilleur proxy accessible
    sans ligne de commande ni dépendance externe.
    """
    try:
        metal = ctypes.CDLL(
            "/System/Library/Frameworks/Metal.framework/Metal"
        )
        objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")

        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.objc_getClass.restype = ctypes.c_void_p

        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p

        # objc_msgSend : on changera dynamiquement le restype
        objc_msgSend = objc.objc_msgSend

        metal.MTLCreateSystemDefaultDevice.argtypes = []
        metal.MTLCreateSystemDefaultDevice.restype = ctypes.c_void_p

        device = metal.MTLCreateSystemDefaultDevice()
        if not device:
            return False

        sel_responds = objc.sel_registerName(b"respondsToSelector:")
        sel_recommended = objc.sel_registerName(b"recommendedMaxWorkingSetSize")
        #sel_hasUnifiedMemory = objc.sel_registerName(b"hasUnifiedMemory")

        # bool respondsToSelector:
        objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        objc_msgSend.restype = ctypes.c_bool

        if not objc_msgSend(device, sel_responds, sel_recommended):
            return False

        # uint64 recommendedMaxWorkingSetSize
        objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        objc_msgSend.restype = ctypes.c_uint64
        working_set_size = int(objc_msgSend(device, sel_recommended))

        if working_set_size >= threshold_bytes:
            return True

        # Optionnel : sur certains Macs, la mémoire unifiée peut être grande,
        # mais recommendedMaxWorkingSetSize plus conservateur.
        # On reste volontairement strict : sinon False.
        return False

    except Exception:
        return False


# ======================================================================
# LINUX : best effort sans dépendances externes
# ======================================================================

def _has_gpu_linux_best_effort(threshold_bytes):
    """
    Best effort Linux sans subprocess :
      - AMD/Intel via /sys/class/drm/.../mem_info_vram_total quand dispo
      - NVIDIA via /proc/driver/nvidia/gpus/.../information
    """
    try:
        # 1) AMD / certains drivers exposent mem_info_vram_total
        for path in glob.glob("/sys/class/drm/card*/device/mem_info_vram_total"):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    value = int(f.read().strip())
                    if value >= threshold_bytes:
                        return True
            except Exception:
                pass

        # 2) Fallback NVIDIA via /proc/driver/nvidia/gpus/*/information
        # Le format varie selon les drivers.
        for path in glob.glob("/proc/driver/nvidia/gpus/*/information"):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read()

                # Exemples possibles :
                # "Video BIOS: ..."
                # "Model: ..."
                # parfois "FB Memory Usage" n'est pas ici selon versions
                # donc on tente quelques motifs.
                import re

                patterns = [
                    r"FB Memory\s*:\s*(\d+)\s*MiB",
                    r"FB Memory Usage\s*Total\s*:\s*(\d+)\s*MiB",
                    r"Memory\s*:\s*(\d+)\s*MB",
                ]
                for pat in patterns:
                    m = re.search(pat, txt, flags=re.IGNORECASE)
                    if m:
                        mem_mb = int(m.group(1))
                        if mem_mb * 1024 * 1024 >= threshold_bytes:
                            return True
            except Exception:
                pass

        return False

    except Exception:
        return False
