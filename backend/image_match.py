"""Matching d'image montre → variante EveryWatch, via CLIP local (open_clip).

But : quand une réf a plusieurs sous-variantes (cadrans/marqueurs différents) qu'on
ne peut PAS distinguer en texte (EveryWatch dit « Silver » pour bâtons/romains/diamants),
on compare la PHOTO de notre montre aux images canoniques des variantes et on prend
la plus proche (cosine sur les embeddings CLIP).

Chargé PARESSEUSEMENT : importer ce module ne charge pas torch tant qu'on n'appelle
pas le matcher → le reste du projet (collecte, API, pricing Chrono24) tourne sans torch.
Le modèle est mis en cache après le 1er appel.
"""
import io

import numpy as np

# ViT-L-14 : ViT-B-32 ne distinguait PAS les marqueurs fins (romains/bâtons/diamants,
# tout à ~0.70). Le L-14 sépare correctement (validé sur 279384RBR → -0009 romains).
_MODEL_NAME = "ViT-L-14"
_PRETRAINED = "laion2b_s32b_b82k"
_model = None
_preprocess = None


def _load():
    global _model, _preprocess
    if _model is None:
        import torch  # noqa: F401 (open_clip en a besoin)
        import open_clip
        _model, _, _preprocess = open_clip.create_model_and_transforms(
            _MODEL_NAME, pretrained=_PRETRAINED)
        _model.eval()
    return _model, _preprocess


def crop_center(im, frac=0.7):
    """Recadre sur le CADRAN pour se concentrer sur les marqueurs (ce qui distingue
    les sous-variantes). Étape clé : on détecte d'abord la montre (bbox du contenu,
    ni fond blanc watchnian ni fond noir EveryWatch) pour NORMALISER l'échelle — sans
    ça, une montre qui remplit son image vs une petite dans un cadre portrait donnent
    des zooms différents et le match échoue. Puis carré central = le disque du cadran."""
    im = im.convert("RGB")
    a = np.asarray(im.convert("L"))
    fg = (a > 25) & (a < 238)
    ys, xs = np.where(fg)
    if len(xs) >= 20:
        im = im.crop((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())))
    w, h = im.size
    s = int(min(w, h) * frac)
    cx, cy = w // 2, h // 2
    return im.crop((cx - s // 2, cy - s // 2, cx + s // 2, cy + s // 2))


def embed(pil_images, dial_crop=True):
    """Embeddings CLIP L2-normalisés (matrice n×d) d'une liste d'images PIL."""
    import torch
    model, preprocess = _load()
    tensors = []
    for im in pil_images:
        im = im.convert("RGB")
        if dial_crop:
            im = crop_center(im)
        tensors.append(preprocess(im))
    with torch.no_grad():
        feats = model.encode_image(torch.stack(tensors))
        feats = feats / feats.norm(dim=-1, keepdim=True)
    return feats.cpu().numpy()


def best_match(query_img, candidate_imgs, dial_crop=True):
    """Renvoie (index, score, marge) : la candidate la plus proche de query_img.
    `marge` = écart de similarité entre la 1re et la 2e candidate → sert de mesure
    de CONFIANCE (si les 2 meilleures sont ex æquo, le match est douteux → fallback)."""
    if not candidate_imgs:
        return None, 0.0, 0.0
    embs = embed([query_img] + list(candidate_imgs), dial_crop=dial_crop)
    q, cands = embs[0], embs[1:]
    sims = cands @ q
    order = np.argsort(sims)[::-1]
    best = int(order[0])
    second = float(sims[order[1]]) if len(order) > 1 else 0.0
    return best, float(sims[best]), float(sims[best] - second)


def load_image(data: bytes):
    """bytes → image PIL (ou None si illisible)."""
    try:
        return __import__("PIL.Image", fromlist=["Image"]).open(io.BytesIO(data))
    except Exception:
        return None
