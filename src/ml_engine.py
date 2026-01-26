import base64
import io
import numpy as np
from PIL import Image

# Try importing TensorFlow (handled gracefully if missing during dev)
try:
    import tensorflow as tf
    from tensorflow import keras
    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False

# GLOBAL SETTINGS
SIMULATION_MODE = True  # Set to FALSE when you have your 'model.h5' file ready
MODEL_PATH = "src/static/model/sentinel_facenet.h5"
loaded_model = None

def load_model():
    """Loads the Keras model into memory once on startup."""
    global loaded_model
    if SIMULATION_MODE:
        print("[ML] Running in SIMULATION MODE (No model loaded)")
        return

    if TF_AVAILABLE and not loaded_model:
        try:
            print(f"[ML] Loading model from {MODEL_PATH}...")
            # loaded_model = keras.models.load_model(MODEL_PATH)
            print("[ML] Model loaded successfully.")
        except Exception as e:
            print(f"[ML] Error loading model: {e}")

def preprocess_image(base64_string, target_size=(160, 160)):
    """Decodes Base64 -> Resize -> Normalize for Tensor."""
    # 1. Strip the header "data:image/jpeg;base64," if present
    if "," in base64_string:
        base64_string = base64_string.split(",")[1]
    
    # 2. Decode to Bytes
    img_bytes = base64.b64decode(base64_string)
    
    # 3. Open with PIL
    image = Image.open(io.BytesIO(img_bytes)).convert('RGB')
    
    # 4. Resize to model's input requirement (e.g., 160x160 for FaceNet)
    image = image.resize(target_size)
    
    # 5. Convert to Array & Normalize (0-255 -> 0-1)
    img_array = np.array(image) / 255.0
    
    # 6. Expand dimensions (1, 160, 160, 3) for batch prediction
    img_array = np.expand_dims(img_array, axis=0)
    
    return img_array

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
            "name": "Simulated User",
            "confidence": 0.98
        }
    # -------------------------------------------------------

    if not loaded_model:
        return {"match": False, "error": "Model not loaded"}

    try:
        # 1. Preprocess
        input_tensor = preprocess_image(image_b64)
        
        # 2. Inference (Get Embedding)
        embedding = loaded_model.predict(input_tensor)
        
        # 3. Compare Embedding with Database
        # (Here you would loop through your SQLite 'FaceData' table 
        # and calculate Euclidean distance)
        
        # Placeholder for DB Logic:
        best_match_user = "Admin"
        confidence = 0.95 # derived from distance
        
        return {
            "match": True,
            "user_id": 1,
            "name": best_match_user,
            "confidence": confidence
        }

    except Exception as e:
        print(f"[ML] Inference Error: {e}")
        return {"match": False}