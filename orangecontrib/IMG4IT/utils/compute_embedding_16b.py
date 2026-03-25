import torch
import numpy as np
from torchvision import models, transforms as T
from transformers import AutoModel, AutoImageProcessor
from PIL import Image
import os
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.MetManagement import get_local_store_path
else:
    from orangecontrib.AAIT.utils.MetManagement import get_local_store_path


def load_tif_image(path):
    img = Image.open(path)
    img_np = np.array(img).astype(np.float32) / 65535.0  # Normalisé [0,1]
    if img_np.ndim == 2:  # grayscale
        img_np = np.stack([img_np]*3, axis=0)  # [3, H, W]
    elif img_np.shape[-1] == 3:  # [H, W, 3]
        img_np = img_np.transpose(2, 0, 1)  # [3, H, W]
    return torch.from_numpy(img_np).float()  # [3, H, W]






def compute_dinov2_embedding(list_tif_in,progress_callback=None,argself=None):
    dino_path = get_local_store_path() + "/Models/ComputerVision/dinov2-base"
    dino_model = AutoModel.from_pretrained(dino_path).to(torch.device("cpu")).eval()
    dino_processor = AutoImageProcessor.from_pretrained(dino_path,use_fast=False)
    result_vects=[]
    for idx,element in enumerate(list_tif_in):
        #print(element)
        if progress_callback is not None:
            progress_value = float(100 * (idx + 1) / len(list_tif_in))
            progress_callback(progress_value)
        if argself is not None:
            if argself.stop:
                break

        tensor_img = load_tif_image(element)
        """
           tensor_img: torch.Tensor [3, H, W] en float32 et déjà normalisé dans [0,1]
           On évite tout rescale supplémentaire et on pool les tokens.
           """
        # Le processor attend HWC; on passe en numpy HWC
        img_hwc = tensor_img.permute(1, 2, 0).cpu().numpy()

        # IMPORTANT: éviter le re-rescale (on est déjà en [0,1])
        inputs = dino_processor(images=img_hwc,return_tensors="pt", do_rescale=False)
        inputs = {k: v.to(torch.device("cpu")) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = dino_model(**inputs)  # Pas de get_image_features sur Dinov2Model

            # Deux options courantes pour l’embedding :
            # 1) CLS token (si dispo) : outputs.last_hidden_state[:, 0]
            # 2) Moyenne des patch tokens : mean pooling
            feats = outputs.last_hidden_state.mean(dim=1)  # [B, D]
        result_vects.append(feats.cpu().numpy().squeeze())

    # c est juste une transposee en python
    result_vects_transpose= [list(col) for col in zip(*[row.tolist() for row in result_vects])]
    return result_vects_transpose

def compute_resnet_embedding(list_tif_in,progress_callback=None,argself=None):
    resnet_path = get_local_store_path() + "models/ComputerVision/resnet50/resnet50-0676ba61.pth"
    resnet = models.resnet50()
    state_dict = torch.load(resnet_path, map_location=torch.device("cpu"))
    resnet.load_state_dict(state_dict)
    resnet = resnet.to(torch.device("cpu")).eval()

    resnet_transform = T.Compose([
        T.Resize((224, 224)),
        T.Normalize(mean=[0.485, 0.456, 0.406],
                    std=[0.229, 0.224, 0.225]),
    ])
    result_vects=[]
    for idx,element in enumerate(list_tif_in):
        #print(element)
        if progress_callback is not None:
            progress_value = float(100 * (idx + 1) / len(list_tif_in))
            progress_callback(progress_value)
        if argself is not None:
            if argself.stop:
                break

        tensor_img = load_tif_image(element)
        x = resnet_transform(tensor_img).unsqueeze(0).to(torch.device("cpu"))
        with torch.no_grad():
            features = resnet(x)
            result_vects.append(features.cpu().numpy().squeeze())

    # c est juste une transposee en python
    result_vects_transpose = [list(col) for col in zip(*[row.tolist() for row in result_vects])]
    return result_vects_transpose



