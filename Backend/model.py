import sys
import os
import cv2
import numpy as np
import pandas as pd
 
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATASET_DIR = os.path.join(BASE_DIR, "Datasets")
 
 
def _clean(value):
    """NaN / empty cells -> None (NaN is not valid JSON and breaks the browser's response.json())."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value
 
 
def _norm_hex(value):
    """'ff00aa' / ' #FF00AA ' -> '#FF00AA' so CSS can always use it."""
    value = _clean(value)
    if value is None:
        return None
    value = str(value).strip().lstrip('#')
    return '#' + value.upper()
 
 
# ---------------------- Load Datasets ----------------------
def load_datasets():
    """Loads and validates the necessary datasets."""
    try:
        # Paths are relative to this file, not to the folder the app was started from
        palette_data = pd.read_excel(os.path.join(DATASET_DIR, "color_palate_ds.xlsx"))
        suggestions = pd.read_excel(os.path.join(DATASET_DIR, "suggestions.xlsx"))
 
        palette_data.columns = palette_data.columns.str.strip()
        suggestions.columns = suggestions.columns.str.strip()
 
        # Tidy the cells so season names always match between the two files
        for df in (palette_data, suggestions):
            if 'Season' in df.columns:
                df['Season'] = df['Season'].astype(str).str.strip()
        if 'Hex_Code' in palette_data.columns:
            palette_data['Hex_Code'] = palette_data['Hex_Code'].map(_norm_hex)
        if 'Gender' in suggestions.columns:
            suggestions['Gender'] = suggestions['Gender'].astype(str).str.strip()
        
        required_cols_palette = ['Season', 'Red', 'Green', 'Blue', 'Hex_Code']
        # Ensure 'Gender' column is present in suggestions for frontend filtering
        required_cols_suggestions = ['Season', 'Gender', 'Style', 'Product Link', 'Image Path'] 
        
        if not all(col in palette_data.columns for col in required_cols_palette):
            raise ValueError(f"Missing required columns in color_palate_ds.xlsx. Required: {required_cols_palette}")
        if not all(col in suggestions.columns for col in required_cols_suggestions):
            raise ValueError(f"Missing required columns in suggestions.xlsx. Required: {required_cols_suggestions}")
            
        return palette_data, suggestions
    except FileNotFoundError as e:
        print(f"Error: {e}. Please ensure 'Datasets/color_palate_ds.xlsx' and 'Datasets/suggestions.xlsx' exist.")
        return None, None
    except ImportError as e:
        print(f"Error: {e}. Reading .xlsx needs openpyxl: pip install openpyxl")
        return None, None
    except Exception as e:
        print(f"Error loading datasets: {e}")
        return None, None
 
palette_data, suggestions = load_datasets()
 
# ---------------------- Image Loading / Lighting Helpers ----------------------
MAX_SIDE = 800  # Large photos are scaled down: faster and less sensor noise
 
 
def _load_image_bgr(image_path):
    """
    Loads a JPEG/PNG as an 8-bit BGR image.
    Handles grayscale, 16-bit and transparent (alpha) PNGs, which would
    otherwise turn black behind the face and corrupt the colour reading.
    """
    img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError("Could not read image file (only JPEG and PNG are supported).")
 
    if img.dtype == np.uint16:
        img = (img / 257).astype(np.uint8)
    elif img.dtype != np.uint8:
        img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
 
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.shape[2] == 4:
        alpha = img[:, :, 3:4].astype(np.float32) / 255.0
        bgr = img[:, :, :3].astype(np.float32)
        img = (bgr * alpha + 255.0 * (1.0 - alpha)).astype(np.uint8)
 
    h, w = img.shape[:2]
    scale = MAX_SIDE / float(max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img
 
 
def _skin_mask(bgr):
    """
    Boolean mask of likely skin pixels (YCrCb AND HSV agreement).
    Requiring both colour spaces removes hair, lips-shadow, clothes and background.
    """
    ycrcb = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    cr, cb = ycrcb[:, :, 1], ycrcb[:, :, 2]
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
 
    m_ycc = (cr >= 133) & (cr <= 180) & (cb >= 77) & (cb <= 130)
    m_hsv = ((h <= 25) | (h >= 170)) & (s >= 15) & (s <= 190) & (v >= 40)
    mask = (m_ycc & m_hsv).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return mask.astype(bool)
 
 
def _white_balance(bgr, skin):
    """
    Mild white balance using NON-skin pixels only (background / clothes), so the
    person's own undertone is never "corrected away". Gains are clamped so a
    coloured wall cannot cause a big shift. Skipped when there is too little background.
    """
    other = ~skin
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    usable = other & (gray > 30) & (gray < 225)   # ignore blown-out / black areas
    if usable.sum() < 0.15 * gray.size:
        return bgr
 
    means = np.array([bgr[:, :, c][usable].mean() for c in range(3)], dtype=np.float32)
    gains = means.mean() / np.maximum(means, 1.0)
    gains = np.clip(gains, 0.88, 1.12)
    return np.clip(bgr.astype(np.float32) * gains, 0, 255).astype(np.uint8)
 
 
_FACE_CASCADES = None
 
 
def _detect_face(bgr):
    """Returns the largest detected frontal face as (x, y, w, h), or None."""
    global _FACE_CASCADES
    try:
        if _FACE_CASCADES is None:
            cascade_files = (
                "haarcascade_frontalface_default.xml",
                "haarcascade_frontalface_alt2.xml",
            )
            _FACE_CASCADES = [
                cv2.CascadeClassifier(cv2.data.haarcascades + filename)
                for filename in cascade_files
            ]
        cascades = [cascade for cascade in _FACE_CASCADES if not cascade.empty()]
        if not cascades:
            return None
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        detection_images = (cv2.equalizeHist(gray), gray)
        min_size = max(40, int(min(gray.shape) * 0.10))
        for cascade in cascades:
            for detection_image in detection_images:
                faces = cascade.detectMultiScale(
                    detection_image,
                    scaleFactor=1.1,
                    minNeighbors=5,
                    minSize=(min_size, min_size),
                )
                if len(faces):
                    return tuple(int(v) for v in max(faces, key=lambda f: f[2] * f[3]))
        return None
    except Exception:
        return None
 
 
def _sample_regions(shape, face):
    """Skin sampling boxes (x0, y0, x1, y1): cheeks + forehead if a face was found, else image centre."""
    H, W = shape[:2]
    if face is not None:
        x, y, w, h = face
        boxes = [
            (x + 0.15 * w, y + 0.52 * h, x + 0.38 * w, y + 0.74 * h),   # left cheek
            (x + 0.62 * w, y + 0.52 * h, x + 0.85 * w, y + 0.74 * h),   # right cheek
            (x + 0.32 * w, y + 0.10 * h, x + 0.68 * w, y + 0.26 * h),   # forehead
        ]
    else:
        boxes = [(0.30 * W, 0.30 * H, 0.70 * W, 0.70 * H)]
    return [(max(0, int(a)), max(0, int(b)), min(W, int(c)), min(H, int(d))) for a, b, c, d in boxes]
 
 
# ---------------------- Extract Skin Color ----------------------
def extract_skin_color(image_path, return_face=False):
    """
    Robust skin colour estimate (RGB), designed to ignore lighting effects:
      1. Transparent / grayscale / 16-bit images are normalised, big ones are resized.
      2. Mild white balance from background pixels only.
      3. Face is located; cheeks + forehead are sampled (not hair / eyes / background).
      4. Only skin-coloured pixels are kept (YCrCb + HSV mask).
      5. Shadows and shiny highlights are discarded (middle band of lightness),
         then the MEDIAN colour is taken, which is stable against outliers.
    CLAHE was removed: it exaggerates contrast and shifts the real skin colour.
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found at {image_path}")
 
    img = _load_image_bgr(image_path)
 
    face = _detect_face(img)
    skin = _skin_mask(img)
    img = _white_balance(img, skin)
    skin = _skin_mask(img)  # recompute after balancing
 
    regions = _sample_regions(img.shape, face)
 
    picked = []
    for x0, y0, x1, y1 in regions:
        if x1 <= x0 or y1 <= y0:
            continue
        patch = img[y0:y1, x0:x1].reshape(-1, 3)
        pmask = skin[y0:y1, x0:x1].reshape(-1)
        if pmask.sum() >= 30:
            patch = patch[pmask]
        picked.append(patch)
 
    pixels = np.vstack(picked) if picked else img.reshape(-1, 3)
    if len(pixels) < 30:
        pixels = img.reshape(-1, 3)
 
    # Drop specular highlights (very bright + washed out) and deep shadows
    hsv = cv2.cvtColor(pixels.reshape(-1, 1, 3), cv2.COLOR_BGR2HSV).reshape(-1, 3)
    keep = ~((hsv[:, 2] > 245) & (hsv[:, 1] < 40)) & (hsv[:, 2] > 35)
    if keep.sum() >= 30:
        pixels = pixels[keep]
 
    lab = cv2.cvtColor(pixels.reshape(-1, 1, 3), cv2.COLOR_BGR2LAB).reshape(-1, 3)
    l = lab[:, 0]
    lo, hi = np.percentile(l, [20, 80])          # keep the evenly lit middle band
    band = (l >= lo) & (l <= hi)
    if band.sum() >= 20:
        lab = lab[band]
 
    median_lab = np.median(lab, axis=0).astype(np.uint8)
    median_bgr = cv2.cvtColor(median_lab.reshape(1, 1, 3), cv2.COLOR_LAB2BGR)[0, 0]
    rgb = [int(median_bgr[2]), int(median_bgr[1]), int(median_bgr[0])]
 
    if return_face:
        H, W = img.shape[:2]
        face_box = None
        if face is not None:
            x, y, w, h = face
            face_box = {'x': x / W, 'y': y / H, 'w': w / W, 'h': h / H}
        return rgb, face_box
    return rgb
 
 
# ---------------------- Predict Season ----------------------
def _rgb_to_lab_array(rgb_array):
    """(N, 3) RGB uint8 -> (N, 3) float LAB (L 0-100, a/b centred on 0)."""
    arr = np.asarray(rgb_array, dtype=np.uint8).reshape(-1, 1, 3)
    lab = cv2.cvtColor(arr, cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float32)
    lab[:, 0] = lab[:, 0] * 100.0 / 255.0
    lab[:, 1:] -= 128.0
    return lab
 
 
def predict_undertone(skin_rgb):
    """
    Predicts the season from the skin colour.
    Compared in LAB space (perceptual) with lightness down-weighted, because
    lightness is what changes most with lighting while hue/chroma (a, b) stay stable.
    Each season is scored by the mean distance of its 3 closest palette colours,
    so one odd colour in the dataset cannot decide the result.
    """
    if palette_data is None:
        raise RuntimeError("Palette data is not loaded.")
 
    skin_lab = _rgb_to_lab_array([skin_rgb])[0]
    weights = np.array([0.4, 1.0, 1.0], dtype=np.float32)   # L, a, b
 
    best_season, best_score = None, float('inf')
    for season, group in palette_data.groupby('Season'):
        rgb = group[['Red', 'Green', 'Blue']].to_numpy(dtype=np.float32).clip(0, 255)
        lab = _rgb_to_lab_array(rgb)
        dists = np.sqrt((((lab - skin_lab) * weights) ** 2).sum(axis=1))
        score = float(np.sort(dists)[:3].mean())
        if score < best_score:
            best_score, best_season = score, season
 
    return best_season
 
# ---------------------- Get Season Palette Colors ----------------------
def get_season_palette_colors(season):
    """
    Retrieves all hex codes and RGB values for a given season from the palette data, 
    formatted as a list of dictionaries for frontend use.
    """
    if palette_data is None:
        raise RuntimeError("Palette data is not loaded.")
    
    season_colors = palette_data[palette_data['Season'].str.lower() == season.lower()]
    
    color_list = []
    for _, row in season_colors.iterrows():
        color_list.append({
            'hex_code': row['Hex_Code'],
            # 'name' is used for hover text; uses Color_Name column if present, else the hex
            'name': _clean(row.get('Color_Name')) or row['Hex_Code'],
            'rgb': [int(row['Red']), int(row['Green']), int(row['Blue'])]
        })
    return color_list
 
# ---------------------- Get Suggestions ----------------------
def get_suggestions(season):
    """
    Retrieves a list of suggestions for a given season.
    """
    if suggestions is None:
        raise RuntimeError("Suggestions data is not loaded.")
    
    season_suggestions = suggestions[suggestions['Season'].str.lower() == season.lower()]
    
    # The 'Image Path' column name needs to match your dataset exactly
    image_path_col = 'Image Path' 
    if image_path_col not in season_suggestions.columns:
         # Fallback if 'Image Path' is not the exact column name, try to find one containing 'image'
        image_path_col = next((col for col in season_suggestions.columns if 'image' in col.lower()), None)
        if not image_path_col:
            raise ValueError("No column containing 'image' found in the suggestions dataset.")
    
    suggestions_list = []
    for _, row in season_suggestions.iterrows():
        suggestions_list.append({
            'gender': _clean(row.get('Gender')),
            'style': _clean(row.get('Style')),
            'image_path': _clean(row.get(image_path_col)),
            'product_link': _clean(row.get('Product Link'))
        })
    return suggestions_list
    
# ---------------------- Get ALL Palette Colors (MODIFIED) ----------------------
def get_all_palette_colors():
    """Retrieves all color data (Season, Hex, RGB) from the dataset."""
    if palette_data is None:
        raise RuntimeError("Palette data is not loaded.")
    
    all_colors = []
    for _, row in palette_data.iterrows():
        all_colors.append({
            'season': row['Season'],
            'hex_code': row['Hex_Code'],
            'name': _clean(row.get('Color_Name')) or row['Hex_Code'],
            'rgb': [int(row['Red']), int(row['Green']), int(row['Blue'])]
        })
    return all_colors
 
 
# ---------------------- Combined Prediction Function for API (CORRECTED) ----------------------
def analyze_image_and_get_data(image_path):
    """
    Performs the full analysis pipeline and returns ALL data required by the frontend modal.
    """
    try:
        # 1. Extract skin color (lighting-robust) and where the face is
        skin_rgb, face_box = extract_skin_color(image_path, return_face=True)
        
        # 2. Predict season
        season = predict_undertone(skin_rgb)
        if not season:
            return None, "Could not determine a season match."
        
        # 3. Get predicted season palette and suggestions
        palette = get_season_palette_colors(season)
        style_suggestions = get_suggestions(season)
        
        # 4. GET ALL COLORS (CRITICAL FOR THE TRY-ON GRID)
        all_colors = get_all_palette_colors()
 
        # Return all data fields expected by the frontend
        return {
            'dominant_skin_color_rgb': skin_rgb,
            'face_box': face_box,  # normalised face box (or None) used to centre the try-on image
            'predicted_season': season,
            'palette_colors': palette,
            'suggestions': style_suggestions,
            'all_palette_colors': all_colors  # <--- NEW REQUIRED FIELD
        }, None
        
    except Exception as e:
        return None, str(e)