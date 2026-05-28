import base64
import io
import json
import os
import numpy as np
from PIL import Image
from sqlmodel import Session, select

# Try importing TensorFlow (handled gracefully if missing during dev)
try:
    import tensorflow as tf  # type: ignore[import-not-found]
    from tensorflow import keras  # type: ignore[import-not-found]
    TF_AVAILABLE = True
except ImportError:
    tf = None
    keras = None
    TF_AVAILABLE = False

from src.database import engine, find_best_face_match
from src.table import SystemConfig, FACE_EMBEDDING_DIMENSION

# GLOBAL SETTINGS
SIMULATION_MODE = os.environ.get("SENTINEL_SIMULATION_MODE", "").lower() in {"1", "true", "yes"}
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(BASE_DIR, "src", "static", "model", "sentinel_facenet.h5")
loaded_model = None


class _FallbackFaceModel:
    output_shape = (None, FACE_EMBEDDING_DIMENSION)

    def predict(self, input_tensor, verbose=0):
        image = np.asarray(input_tensor, dtype=np.float32)
        if image.ndim != 4 or image.shape[-1] != 3:
            raise ValueError("Fallback model expects a batched RGB tensor")

        grayscale = (
            image[..., 0] * 0.2989
            + image[..., 1] * 0.5870
            + image[..., 2] * 0.1140
        )
        grayscale = grayscale.reshape(image.shape[0], 16, 10, 8, 20).mean(axis=(2, 4))
        flattened = grayscale.reshape(image.shape[0], FACE_EMBEDDING_DIMENSION)

        norms = np.linalg.norm(flattened, axis=1, keepdims=True)
        norms = np.where(norms == 0.0, 1.0, norms)
        return flattened / norms


def _get_face_match_threshold(default=0.95):
    try:
        with Session(engine) as session:
            config = session.exec(select(SystemConfig)).first()
            if not config or not config.config_json:
                return default

            config_data = json.loads(config.config_json)
            threshold = float(config_data.get("face_match_threshold", default))
            return max(0.0, min(1.0, threshold))
    except Exception:
        return default


def _resolve_model_embedding_dimension(model):
    output_shape = getattr(model, "output_shape", None)
    if isinstance(output_shape, list) and output_shape:
        output_shape = output_shape[0]

    embedding_dim = None
    if isinstance(output_shape, tuple) and output_shape:
        embedding_dim = output_shape[-1]

    if embedding_dim is None and getattr(model, "outputs", None):
        first_output = model.outputs[0]
        output_tensor_shape = getattr(first_output, "shape", None)
        if output_tensor_shape is not None and len(output_tensor_shape) > 0:
            embedding_dim = output_tensor_shape[-1]

    if embedding_dim is None:
        raise ValueError("Unable to determine model embedding dimension")

    return int(embedding_dim)

def load_model():
    """Loads the Keras model into memory once on startup."""
    global loaded_model
    if SIMULATION_MODE:
        print("[ML] Running in SIMULATION MODE (No model loaded)")
        return None

    if loaded_model:
        return loaded_model

    if not os.path.exists(MODEL_PATH):
        print(f"[ML] Model file not found at {MODEL_PATH}; using fallback embedding model.")
        loaded_model = _FallbackFaceModel()
        return loaded_model

    if not TF_AVAILABLE:
        print("[ML] TensorFlow is not available; using fallback embedding model.")
        loaded_model = _FallbackFaceModel()
        return loaded_model

    if keras is None:
        print("[ML] TensorFlow keras binding is unavailable; using fallback embedding model.")
        loaded_model = _FallbackFaceModel()
        return loaded_model

    try:
        print(f"[ML] Loading model from {MODEL_PATH}...")
        loaded_model = keras.models.load_model(MODEL_PATH)
        embedding_dim = _resolve_model_embedding_dimension(loaded_model)
        print(f"[ML] Model embedding dimension: {embedding_dim}")
        if embedding_dim != FACE_EMBEDDING_DIMENSION:
            raise ValueError(
                f"Model embedding dimension {embedding_dim} does not match sqlite-vec dimension {FACE_EMBEDDING_DIMENSION}"
            )
        print("[ML] Model loaded successfully.")
        return loaded_model
    except Exception as e:
        print(f"[ML] Error loading model: {e}; using fallback embedding model.")
        loaded_model = _FallbackFaceModel()
        return loaded_model

def preprocess_image(base64_string, target_size=(160, 160)):
    """Decodes Base64 -> resize -> FaceNet normalization."""
    if "," in base64_string:
        base64_string = base64_string.split(",")[1]

    img_bytes = base64.b64decode(base64_string)
    image = Image.open(io.BytesIO(img_bytes)).convert('RGB')

    face_image = image.resize(target_size)

    img_array = np.asarray(face_image, dtype=np.float32)
    img_array = (img_array - 127.5) / 128.0
    img_array = np.expand_dims(img_array, axis=0)

    return img_array


def _predict_embedding(input_tensor):
    """Return a flattened float embedding vector from the model output."""
    model = load_model()
    if model is None:
        raise RuntimeError("Face embedding model is unavailable")

    embedding = model.predict(input_tensor, verbose=0)
    return np.asarray(embedding, dtype=np.float32).reshape(-1)


def extract_face_embedding(image_b64):
    """Return the embedding vector for a pre-cropped 160x160 face image."""
    return _predict_embedding(preprocess_image(image_b64))

def recognize_face(image_b64):
    """
    Main pipeline: Image -> Preprocess -> Model -> Database Search
    """
    
    # --- SIMULATION LOGIC (For testing UI without model) ---
    if SIMULATION_MODE:
        # Simulate processing delay?
        import time
        # time.sleep(0.5) 
        
        # Determine a fake result (For demo: Always succeed if image is large enough)
        # You can toggle this to "False" to test the "Face Not Found" UI
        return {
            "match": True,
            "user_id": 1,
            "username": "simulated.user",
            "name": "Simulated User",
            "confidence": 0.98
        }
    # -------------------------------------------------------

    try:
        embedding = extract_face_embedding(image_b64)
        match = find_best_face_match(embedding)

        if not match:
            return {"match": False, "error": "No enrolled face vectors found"}

        if float(match.distance) > _get_face_match_threshold():
            return {"match": False, "error": "Face did not meet the similarity threshold"}

        confidence = float(max(0.0, 1.0 / (1.0 + float(match.distance))))

        return {
            "match": True,
            "user_id": match.user_id,
            "username": match.username,
            "name": match.full_name or match.username or "Unknown User",
            "confidence": confidence,
        }

    except Exception as e:
        print(f"[ML] Inference Error: {e}")
        return {"match": False}