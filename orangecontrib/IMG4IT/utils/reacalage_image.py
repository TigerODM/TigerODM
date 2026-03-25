#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import ast
import re
from typing import Tuple

import numpy as np
from scipy.spatial import cKDTree
from scipy import ndimage
from typing import List
import tifffile
from scipy.ndimage import affine_transform
# ============================================================
# Utilitaires image & SIFT (scikit-image)
# ============================================================
def _to_float_gray(img: np.ndarray) -> np.ndarray:
    """Convertit en float32 [0,1] mono-canal pour la détection."""
    im = img
    if im.ndim == 3:
        # si RGB(A), moyenne simple des 3 premiers canaux
        im = im[..., :3].mean(axis=2)
    im = im.astype(np.float32)
    vmin, vmax = float(np.min(im)), float(np.max(im))
    if vmax > vmin:
        im = (im - vmin) / (vmax - vmin)
    else:
        im[:] = 0.0
    return im


def detect_and_describe_sift(img: np.ndarray):
    """
    Retourne (keypoints_xy (N,2), descriptors (N,D)).
    SIFT de scikit-image (présent dans ta liste).
    """
    from skimage.feature import SIFT  # scikit-image==0.25.2
    gray = _to_float_gray(img)
    sift = SIFT()
    sift.detect_and_extract(gray)
    if sift.keypoints is None or len(sift.keypoints) == 0:
        raise RuntimeError("Aucun point SIFT détecté.")
    # skimage keypoints = (row, col) -> (x, y)
    kpts_xy = np.ascontiguousarray(sift.keypoints[:, ::-1], dtype=np.float64)
    desc = np.ascontiguousarray(sift.descriptors, dtype=np.float32)
    return kpts_xy, desc


# ============================================================
# Matching 2-NN + test de ratio de Lowe
# ============================================================
def match_descriptors(desc1: np.ndarray,
                      desc2: np.ndarray,
                      ratio: float = 0.75) -> Tuple[np.ndarray, np.ndarray]:
    """Retourne indices i1 (dans desc1) et i2 (dans desc2) des bons matches."""
    if desc1.size == 0 or desc2.size == 0:
        return np.empty(0, int), np.empty(0, int)
    tree = cKDTree(desc2)
    dists, idxs = tree.query(desc1, k=2, workers=-1)  # (N,2)
    keep = dists[:, 0] < ratio * dists[:, 1]
    i1 = np.nonzero(keep)[0]
    i2 = idxs[keep, 0]
    return i1, i2


# ============================================================
# Estimation rigide SE(2) (rotation + translation, sans scale)
# ============================================================
def kabsch_se2(P: np.ndarray, Q: np.ndarray):
    """
    Estime R (2x2, det=+1) et t (2,) tels que Q ≈ R @ P + t.
    P, Q: (N,2)
    """
    muP = P.mean(axis=0)
    muQ = Q.mean(axis=0)
    P0 = P - muP
    Q0 = Q - muQ
    H = P0.T @ Q0
    U, _, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T
    # Force det(R)=+1 (pas de réflexion)
    if np.linalg.det(R) < 0:
        Vt[1, :] *= -1.0
        R = Vt.T @ U.T
    t = muQ - R @ muP
    return R, t


def apply_se2(R: np.ndarray, t: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Applique x' = R x + t à une liste de points (N,2)."""
    return (pts @ R.T) + t


def invert_se2(R: np.ndarray, t: np.ndarray):
    """Inverse x' = R x + t -> x = R^T (x' - t)."""
    Rinvt = R.T
    tinv = - Rinvt @ t
    return Rinvt, tinv


# ============================================================
# RANSAC pour SE(2)
# ============================================================
def ransac_se2(pts1: np.ndarray,
               pts2: np.ndarray,
               inlier_thresh: float = 3.0,
               min_inliers: int = 12,
               max_trials: int = 2000,
               seed: int = 0):
    """
    RANSAC sur correspondances 2D (pts1 <-> pts2).
    inlier_thresh en pixels. pts2 ≈ R @ pts1 + t
    """
    rng = np.random.default_rng(seed)
    N = len(pts1)
    if N < 2:
        raise ValueError("Pas assez de correspondances pour RANSAC.")

    idx_all = np.arange(N)
    best_count = 0
    best_inliers = None
    best_model = None

    for _ in range(max_trials):
        s = rng.choice(idx_all, size=2, replace=False)
        P = pts1[s]
        Q = pts2[s]
        try:
            R, t = kabsch_se2(P, Q)
        except np.linalg.LinAlgError:
            continue

        pred = apply_se2(R, t, pts1)
        err = np.linalg.norm(pred - pts2, axis=1)
        inliers = err < inlier_thresh
        count = int(inliers.sum())

        if count > best_count:
            best_count = count
            best_inliers = inliers
            best_model = (R, t)

    # ⚠️ correction ici: pas de parenthèse surnuméraire
    if best_model is None or best_count < max(4, min_inliers):
        raise RuntimeError(f"RANSAC a échoué (inliers={best_count}).")

    Rf, tf = kabsch_se2(pts1[best_inliers], pts2[best_inliers])
    return Rf, tf, best_inliers


# ============================================================
# Pipeline principal d'estimation (ref -> mov)
# ============================================================
def register_rigid(image_ref: np.ndarray,
                   image_mov: np.ndarray,
                   ratio: float = 0.75,
                   ransac_thresh: float = 3.0,
                   min_inliers: int = 12,
                   seed: int = 0):
    """
    Estime la transformée **ref -> mov** (points de ref vers points de mov).
    Retourne:
      angle_rad_ref2mov, (tx, ty) (ref->mov), (R, t), inliers_mask
    """
    k1, d1 = detect_and_describe_sift(image_ref)
    k2, d2 = detect_and_describe_sift(image_mov)
    i1, i2 = match_descriptors(d1, d2, ratio=ratio)
    if len(i1) < 4:
        raise RuntimeError("Trop peu de correspondances après ratio test.")
    P = k1[i1]  # ref
    Q = k2[i2]  # mov
    R, t, inliers = ransac_se2(P, Q,
                               inlier_thresh=ransac_thresh,
                               min_inliers=min_inliers,
                               seed=seed)
    angle = float(np.arctan2(R[1, 0], R[0, 0]))
    tx, ty = float(t[0]), float(t[1])
    return angle, (tx, ty), (R, t), inliers


# ============================================================
# Application image (warp NN, taille inchangée, cval=0)
# ============================================================
def parse_transform_string(transform_str: str):
    """
    Parse une chaîne décrivant une transformation 2D rigide.
    Renvoie (R, t) en coordonnées (x,y).
    Formats acceptés:
      - "angle_deg=..., tx=..., ty=..."
      - "angle_rad=..., tx=..., ty=..."
      - "R=[[a,b],[c,d]]; t=[tx,ty]"   (espaces et retours ligne acceptés)
    """
    s = transform_str.strip()

    # --- utilitaire: extraire un bloc bracketé en comptant les crochets ---
    def _extract_bracket_block(text: str, start_idx: int) -> tuple[str, int]:
        """
        text[start_idx] doit être '['. Retourne (bloc_inclus, end_idx_exclusif)
        où bloc_inclus inclut les crochets externes, et end_idx_exclusif est
        l'index du premier caractère après le bloc.
        """
        if start_idx < 0 or start_idx >= len(text) or text[start_idx] != '[':
            raise ValueError("Extraction bracket: index invalide ou pas de '[' au start.")
        depth = 0
        for i in range(start_idx, len(text)):
            ch = text[i]
            if ch == '[':
                depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0:
                    return text[start_idx:i+1], i+1
        raise ValueError("Crochets non équilibrés dans la chaîne.")

    # --- cas 1 : R=... ; t=... ---
    if "R=" in s and "t=" in s:
        # Localiser "R=" puis extraire le bloc bracketé complet qui suit
        r_pos = s.find("R=")
        # avancer jusqu'au premier '[' après "R="
        r_brack = s.find('[', r_pos)
        if r_brack == -1:
            raise ValueError("Format 'R=...; t=...' mal formé (pas de '[' après R=).")
        R_str, after_R = _extract_bracket_block(s, r_brack)

        # Localiser "t=" puis extraire le bloc bracketé complet qui suit
        t_pos = s.find("t=", after_R)  # on autorise t après R
        if t_pos == -1:
            # si pas trouvé après_R, réessayer depuis le début (ordre inverse toléré)
            t_pos = s.find("t=")
            if t_pos == -1:
                raise ValueError("Format 'R=...; t=...' mal formé (t= manquant).")
        t_brack = s.find('[', t_pos)
        if t_brack == -1:
            raise ValueError("Format 'R=...; t=...' mal formé (pas de '[' après t=).")
        t_str, _ = _extract_bracket_block(s, t_brack)

        # Évaluer littéralement
        R = np.asarray(ast.literal_eval(R_str), dtype=np.float64)
        t = np.asarray(ast.literal_eval(t_str), dtype=np.float64).reshape(2)

        if R.shape != (2, 2):
            raise ValueError(f"R doit être 2x2, obtenu {R.shape}.")
        if t.shape != (2,):
            raise ValueError(f"t doit être de taille 2, obtenu {t.shape}.")
        return R, t

    # --- cas 2 : angle_* + tx/ty ---
    m_ang_deg = re.search(r"angle_deg\s*=\s*([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)", s)
    m_ang_rad = re.search(r"angle_rad\s*=\s*([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)", s)
    if m_ang_deg:
        angle = float(m_ang_deg.group(1)) * np.pi / 180.0
    elif m_ang_rad:
        angle = float(m_ang_rad.group(1))
    else:
        raise ValueError("Angle manquant (angle_deg=... ou angle_rad=...).")

    m_tx = re.search(r"tx\s*=\s*([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)", s)
    m_ty = re.search(r"ty\s*=\s*([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)", s)
    if not (m_tx and m_ty):
        raise ValueError("tx et/ou ty manquants.")
    tx = float(m_tx.group(1))
    ty = float(m_ty.group(1))

    c, si = np.cos(angle), np.sin(angle)
    R = np.array([[c, -si],
                  [si,  c]], dtype=np.float64)
    t = np.array([tx, ty], dtype=np.float64)
    return R, t


def _xy_to_rc_transform(R_xy: np.ndarray, t_xy: np.ndarray):
    """
    Convertit une transformée en coordonnées (x,y) vers (row,col).
    v_rc = P * v_xy, avec P = [[0,1],[1,0]] (swap x<->y)
    En rc: v'_rc = (P R P) v_rc + (P t)
    """
    P = np.array([[0.0, 1.0],
                  [1.0, 0.0]], dtype=np.float64)
    R_rc = P @ R_xy @ P
    t_rc = P @ t_xy
    return R_rc, t_rc


def _affine_params_for_scipy(R_xy: np.ndarray, t_xy: np.ndarray):
    """
    Pour ndimage.affine_transform (qui attend la transformée **inverse**):
      input_rc = M @ output_rc + offset
    avec M = (R_rc)^(-1), offset = - (R_rc)^(-1) * t_rc
    """
    R_rc, t_rc = _xy_to_rc_transform(R_xy, t_xy)
    Rinverse = np.linalg.inv(R_rc)
    M = Rinverse
    offset = - Rinverse @ t_rc
    return M, offset


def _warp_single_channel_nn(img2d: np.ndarray, M: np.ndarray, offset: np.ndarray):
    """
    Applique affine_transform (NN) sur un canal 2D.
    Conserve la taille, remplit en 0.
    """
    return ndimage.affine_transform(
        img2d,
        matrix=M,
        offset=offset,
        order=0,           # plus proche voisin
        mode='constant',
        cval=0.0,
        output_shape=img2d.shape,
        prefilter=False
    )


def apply_transform_to_image_file(in_path: str, out_path: str, transform_str: str):
    """
    Applique rotation+translation à l'image d'entrée avec interpolation de qualité (cubic),
    conserve la taille, gère bords en reflect, et conserve dtype/canaux.

    transform_str décrit la **transformée directe**: x' = R x + t (en (x,y)).
    """


    img = tifffile.imread(in_path)
    orig_dtype = img.dtype

    R, t = parse_transform_string(transform_str)

    # Pour scipy.ndimage.affine_transform:
    # output[x] = input(matrix @ x + offset)
    # donc on lui donne la transform inverse (déjà ce que fait ta fonction)
    M, offset = _affine_params_for_scipy(R, t)

    def _warp_single_channel_highq(ch: np.ndarray) -> np.ndarray:
        # ✅ calc en float32 pour éviter quantification/arrondis structurés
        ch_f = ch.astype(np.float32, copy=False)

        warped_f = affine_transform(
            ch_f,
            matrix=M,
            offset=offset,
            output_shape=ch.shape,
            order=3,              # ⭐ cubic (bon compromis qualité/temps)
            mode="reflect",       # ⭐ mieux que constant=0 dans beaucoup de cas
            cval=0.0,
            prefilter=True,       # important pour order>1
        )

        # ✅ re-cast propre au dtype d'origine
        if np.issubdtype(orig_dtype, np.integer):
            info = np.iinfo(orig_dtype)
            warped_f = np.clip(warped_f, info.min, info.max)
            return warped_f.astype(orig_dtype)
        else:
            return warped_f.astype(orig_dtype)

    if img.ndim == 2:
        warped = _warp_single_channel_highq(img)

    elif img.ndim == 3:
        H, W, C = img.shape
        out = np.empty((H, W, C), dtype=orig_dtype)
        for c in range(C):
            out[..., c] = _warp_single_channel_highq(img[..., c])
        warped = out

    else:
        raise ValueError(f"Dimension d'image non gérée: {img.ndim}D")

    tifffile.imwrite(out_path, warped)
    return out_path



# ============================================================
# I/O TIF
# ============================================================
def read_tiff(path: str) -> np.ndarray:
    import tifffile
    return tifffile.imread(path)


def write_tiff(path: str, arr: np.ndarray):
    import tifffile
    tifffile.imwrite(path, arr)


# ============================================================
# Démo : création d'un exemple, estimation, application
# ============================================================
def _make_synthetic_image(h=512, w=512, dtype=np.uint16) -> np.ndarray:
    """
    Crée une image synthétique avec motifs nets adaptés aux features (grille, croix, disques).
    dtype uint16 par défaut (pour tester la conservation 16 bits).
    """
    img = np.zeros((h, w), dtype=dtype)

    # Grille
    for r in range(20, h, 40):
        img[r:r+2, :] = np.iinfo(dtype).max // 4
    for c in range(20, w, 40):
        img[:, c:c+2] = np.iinfo(dtype).max // 4

    # Rectangles
    img[80:160, 80:200] = np.iinfo(dtype).max // 2
    img[300:420, 300:460] = np.iinfo(dtype).max // 3

    # Croix
    img[220:222, 100:412] = np.iinfo(dtype).max
    img[60:440, 250:252] = np.iinfo(dtype).max

    # Disques approximés
    yy, xx = np.ogrid[:h, :w]
    img[(yy - 380)**2 + (xx - 120)**2 <= 30**2] = np.iinfo(dtype).max
    img[(yy - 120)**2 + (xx - 380)**2 <= 40**2] = np.iinfo(dtype).max // 2

    return img


def _transform_string_from_angle_tx_ty(angle_deg: float, tx: float, ty: float) -> str:
    return f"angle_deg={angle_deg}, tx={tx}, ty={ty}"


def demo_register_and_apply():

    # 1) Créer une image de référence (uint16 mono)
    ref = _make_synthetic_image(dtype=np.uint16)
    write_tiff("ref.tif", ref)

    # 2) Générer l'image mobile en lui appliquant une transfo connue (forward)
    angle_true_deg = 3.0
    tx_true = 12.0
    ty_true = -7.0
    transform_true_str = _transform_string_from_angle_tx_ty(angle_true_deg, tx_true, ty_true)
    apply_transform_to_image_file("ref.tif", "mov.tif", transform_true_str)

    # 3) Charger les deux images et estimer la transfo **ref -> mov**
    ref_img = read_tiff("ref.tif")
    mov_img = read_tiff("mov.tif")

    angle_est_rad, (tx_est, ty_est), (R_est, t_est), inliers = register_rigid(
        ref_img, mov_img,
        ratio=0.75,
        ransac_thresh=3.0,
        min_inliers=12,
        seed=0
    )

    angle_est_deg = np.degrees(angle_est_rad)

    # 4) Calculer l'inverse pour obtenir **mov -> ref** (à appliquer à mov pour l'aligner sur ref)
    R_m2r, t_m2r = invert_se2(R_est, t_est)
    angle_m2r_deg = np.degrees(np.arctan2(R_m2r[1, 0], R_m2r[0, 0]))

    # 5) Appliquer l'estimation inverse à mov
    transform_est_inv_str = f"R={R_m2r.tolist()}; t={[float(t_m2r[0]), float(t_m2r[1])]}"
    apply_transform_to_image_file("mov.tif", "mov_aligned.tif", transform_est_inv_str)
    mov_aligned = read_tiff("mov_aligned.tif")

    # 6) Évaluer l'alignement (erreurs et visuels)
    mae_before = float(np.mean(np.abs(mov_img.astype(np.int64) - ref_img.astype(np.int64))))
    mae_after  = float(np.mean(np.abs(mov_aligned.astype(np.int64) - ref_img.astype(np.int64))))

    print("=== Vérité terrain (appliquée pour générer mov) ===")
    print(f"  angle_true_deg = {angle_true_deg:.4f}°, tx_true = {tx_true:.4f}, ty_true = {ty_true:.4f}")
    print("=== Estimation (ref -> mov) ===")
    print(f"  angle_est_deg  = {angle_est_deg:.4f}°, tx_est  = {tx_est:.4f}, ty_est  = {ty_est:.4f}")
    print(f"  inliers = {int(inliers.sum())}")
    print("=== Inverse estimé (mov -> ref) appliqué à mov ===")
    print(f"  angle_inv_deg  = {angle_m2r_deg:.4f}°, t_inv = ({float(t_m2r[0]):.4f}, {float(t_m2r[1]):.4f})")
    print("=== MAE (différence absolue moyenne) ===")
    print(f"  avant alignement : {mae_before:.2f}")
    print(f"  après  alignement: {mae_after:.2f}")

    # Aperçu PNG facultatif (si matplotlib est dispo)
    try:
        import matplotlib.pyplot as plt
        fig, axs = plt.subplots(2, 2, figsize=(10, 10))
        axs[0, 0].imshow(ref_img, cmap='gray')
        axs[0, 0].set_title("ref.tif"); axs[0, 0].axis('off')
        axs[0, 1].imshow(mov_img, cmap='gray')
        axs[0, 1].set_title("mov.tif (généré)"); axs[0, 1].axis('off')
        axs[1, 0].imshow(mov_aligned, cmap='gray')
        axs[1, 0].set_title("mov_aligned.tif (estimé)"); axs[1, 0].axis('off')
        diff = np.abs(mov_aligned.astype(np.int64) - ref_img.astype(np.int64))
        axs[1, 1].imshow(diff, cmap='gray')
        axs[1, 1].set_title(f"|aligned - ref|  (MAE={mae_after:.1f})"); axs[1, 1].axis('off')
        plt.tight_layout()
        plt.savefig("demo_preview.png", dpi=120)
        print("Aperçu écrit : demo_preview.png")
    except Exception as e:
        print(f"error : {e}")

# ============================================================
# Fourier–Mellin (rotation + translation) via FFT
#   - Rotation: phase correlation on polar FFT magnitude
#   - Translation: phase correlation on spatial domain after derotation
# ============================================================

def _phase_correlation_shift(a: np.ndarray, b: np.ndarray) -> Tuple[int, int]:
    """Return integer (dy, dx) shift such that shifting b by (dy, dx) best matches a.
    Convention verified: if a = shift(b, s) (wrap), returns s.
    """
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    A = np.fft.fft2(a)
    B = np.fft.fft2(b)
    R = A * np.conj(B)
    R /= np.maximum(np.abs(R), 1e-9)
    r = np.fft.ifft2(R)
    r = np.abs(r)
    maxpos = np.unravel_index(np.argmax(r), r.shape)
    dy, dx = maxpos
    if dy > r.shape[0] // 2:
        dy -= r.shape[0]
    if dx > r.shape[1] // 2:
        dx -= r.shape[1]
    return int(dy), int(dx)


def _log_polar_mag_fft(img: np.ndarray, n_angles: int = 720, n_radii: int | None = None) -> np.ndarray:
    """Compute log-polar representation of FFT magnitude (translation invariant).
    Uses a simple sampler with ndimage.map_coordinates (no OpenCV dependency).
    Output shape: (n_angles, n_radii)
    """
    im = _to_float_gray(img)
    h, w = im.shape
    # Hanning window to reduce edge effects
    win_y = np.hanning(h).astype(np.float32)
    win_x = np.hanning(w).astype(np.float32)
    imw = im * win_y[:, None] * win_x[None, :]

    F = np.fft.fftshift(np.fft.fft2(imw))
    mag = np.log1p(np.abs(F)).astype(np.float32)

    cy = (h - 1) / 2.0
    cx = (w - 1) / 2.0
    max_r = min(cy, cx)

    if n_radii is None:
        n_radii = int(max_r)

    # radii in log space (avoid 0)
    r0 = 1.0
    radii = np.exp(np.linspace(np.log(r0), np.log(max_r), n_radii)).astype(np.float32)
    angles = np.linspace(0, 2 * np.pi, n_angles, endpoint=False).astype(np.float32)

    # meshgrid: angles x radii
    rr = radii[None, :]
    aa = angles[:, None]
    ys = cy + rr * np.sin(aa)
    xs = cx + rr * np.cos(aa)

    coords = np.vstack([ys.ravel(), xs.ravel()])
    lp = ndimage.map_coordinates(mag, coords, order=1, mode="wrap").reshape(n_angles, n_radii)
    return lp


def register_rigid_fourier_mellin(
    ref: np.ndarray,
    mov: np.ndarray,
    n_angles: int = 720,
    n_radii: int | None = None,
) -> Tuple[float, Tuple[float, float], Tuple[np.ndarray, np.ndarray], np.ndarray]:
    """Estimate rigid transform (rotation + translation) between ref and mov using Fourier–Mellin.
    Returns the same structure as register_rigid: (angle_rad, (tx, ty), (R, t), inliers)
    Convention: R,t map points in ref -> mov (x' = R x + t).
    """
    # --- rotation estimation (translation invariant) ---
    lp_ref = _log_polar_mag_fft(ref, n_angles=n_angles, n_radii=n_radii)
    lp_mov = _log_polar_mag_fft(mov, n_angles=n_angles, n_radii=n_radii)

    # shift between log-polar images gives rotation (and scale if we used log-radius shift; ignored here)
    d_angle, d_r = _phase_correlation_shift(lp_mov, lp_ref)  # ref -> mov in polar
    # Convert angle shift (rows) to degrees
    angle_deg = - (d_angle * 360.0 / float(n_angles))

    # ======== MODIF UNIQUE: interdire rotations hors [-90, +90] ========
    # Ramène l'angle dans [-180, 180)
    angle_deg = ((angle_deg + 180.0) % 360.0) - 180.0
    # Puis force dans [-90, 90] en retranchant/ajoutant 180 (interdit +/-90..180)
    if angle_deg > 90.0:
        angle_deg -= 180.0
    elif angle_deg < -90.0:
        angle_deg += 180.0
    # ================================================================

    angle_rad = float(np.deg2rad(angle_deg))

    # --- derotate mov to estimate translation in derotated coordinates ---
    mov_derot = ndimage.rotate(_to_float_gray(mov), angle=-angle_deg, reshape=False, order=1, mode="nearest")
    ref_f = _to_float_gray(ref)

    dy, dx = _phase_correlation_shift(mov_derot, ref_f)  # ref -> mov_derot
    tx_rot = float(dx)
    ty_rot = float(dy)

    # Translation in original coordinates: t = R(theta) @ t_rot
    c = float(np.cos(angle_rad))
    s = float(np.sin(angle_rad))
    R = np.array([[c, -s], [s, c]], dtype=np.float32)
    t_rot = np.array([tx_rot, ty_rot], dtype=np.float32)
    t = (R @ t_rot).astype(np.float32)

    # Dummy inliers to keep output shape compatible
    inliers = np.array([True], dtype=bool)
    return angle_rad, (float(t[0]), float(t[1])), (R, t), inliers


def batch_process_tiff_register(
    ref_image: List[str],
    mov_image: List[str],
    progress_callback=None,
    argself=None,
    use_fourier_mellin: bool = False):
    result=[]


    for i in range(len(ref_image)):
        print(i,"/",len(ref_image))
        try:
            if progress_callback is not None:
                progress_value = float(100 * (i + 1) / len(ref_image))
                progress_callback(progress_value)
            if argself is not None:
                if argself.stop:
                    break

            ref = read_tiff(ref_image[i])
            mov = read_tiff(mov_image[i])
            if use_fourier_mellin:
                angle_rad, (tx, ty), (R, t), inliers = register_rigid_fourier_mellin(ref, mov)

            else:
                angle_rad, (tx, ty), (R, t), inliers = register_rigid(ref, mov, ransac_thresh=5.0, min_inliers=8)
                print("verifier si je dois bien transposer (= inverser la rotation ) pour sift")
                # peut etre faire une transposée ici (angle NOK?)
            R_inv, t_inv = invert_se2(R, t)
            # pas sur qu il faillee transposer pour sift
            R_inv = np.transpose(R_inv)

            result.append(f"R={R_inv.tolist()}; t={[float(t_inv[0]), float(t_inv[1])]}")
        except Exception as e:
            result.append(f"error -> {e}")
        #print(result)
    return result

# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    print("uncomment what you want")
    # genere une image fictive est lance le recalage
    demo_register_and_apply()


    # a partir d'image
    # ref = read_tiff("mon_ref.tif")
    # mov = read_tiff("mon_mov.tif")
    # angle_rad, (tx, ty), (R, t), inliers = register_rigid(ref, mov, ransac_thresh=5.0, min_inliers=12)
    # R_inv, t_inv = invert_se2(R, t)
    # apply_transform_to_image_file("mon_mov.tif", "mon_mov_aligned.tif",
    #                               f"R={R_inv.tolist()}; t={[float(t_inv[0]), float(t_inv[1])]}")
