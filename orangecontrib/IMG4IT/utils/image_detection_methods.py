import cv2

# Classe de base (Interface) que toutes les futures méthodes devront respecter
class BaseCircleDetector:
    def process(self, image_path, params):
        raise NotImplementedError("La méthode process doit être implémentée.")


# Implémentation de la méthode Hough
class HoughDetector(BaseCircleDetector):
    def process(self, image_path, params):
        img = cv2.imread(image_path, -1)
        if img is None: return 0

        # Prétraitement
        if img.dtype == 'uint16':
            img_8bit = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX).astype('uint8')
        elif len(img.shape) == 3:
            img_8bit = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            img_8bit = img.astype('uint8')

        img_blurred = cv2.GaussianBlur(img_8bit, (9, 9), 2)

        # Extraction des paramètres sécurisée
        minDist = int(params.get('minDist', 12))
        param1 = int(params.get('param1', 50))
        param2 = int(params.get('param2', 20))
        minRadius = int(params.get('minRadius', 11))
        maxRadius = int(params.get('maxRadius', 18))

        circles = cv2.HoughCircles(
            img_blurred, cv2.HOUGH_GRADIENT, dp=1,
            minDist=minDist, param1=param1, param2=param2,
            minRadius=minRadius, maxRadius=maxRadius
        )

        return circles.shape[1] if circles is not None else 0


# Implémentation future (Exemple : Deep Learning, Blob Detection...)
class BlobDetector(BaseCircleDetector):
    def process(self, image_path, params):
        # TODO: Implémenter SimpleBlobDetector ici plus tard
        pass


# Dictionnaire central (Factory) pour lier le nom de l'UI à la classe
DETECTORS = {
    "Hough Transform": HoughDetector(),
    "Blob Detection": BlobDetector()
}


# --- FONCTION POUR LE THREAD ---
def run_detection_thread(data, image_col_name, method_name, params):
    """Fonction exécutée en arrière-plan par le thread."""
    detector = DETECTORS.get(method_name)
    if not detector:
        raise ValueError(f"Méthode {method_name} non reconnue.")

    results = []
    # Logique simplifiée : on suppose que 'data' contient les chemins d'images
    # A adapter selon la structure exacte de ta Table Orange
    for row in data:
        img_path = str(row[image_col_name])
        nb_billes = detector.process(img_path, params)
        results.append(nb_billes)

    # Ici, tu reconstruirais une Table Orange avec les résultats
    # return [new_table, meta_infos]
    return [results, {"status": "success"}]