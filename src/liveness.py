import base64
import io
import os
import secrets
from typing import Dict, List, Optional

import numpy as np
from PIL import Image

try:
    import tensorflow as tf  # type: ignore[import-not-found]
    from tensorflow import keras  # type: ignore[import-not-found]
    TF_AVAILABLE = True
except ImportError:
    tf = None
    keras = None
    TF_AVAILABLE = False


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVENESS_MODEL_PATH = os.path.join(BASE_DIR, "src", "static", "model", "sentinel_liveness_cnn.h5")
CHALLENGE_TYPES = ("blink", "turn_left", "turn_right", "nod")
_loaded_model = None


def choose_liveness_challenge() -> Dict[str, str]:
    challenge = secrets.choice(CHALLENGE_TYPES)
    prompts = {
        "blink": "Blink once, then hold still.",
        "turn_left": "Turn your head slightly to the left, then center.",
        "turn_right": "Turn your head slightly to the right, then center.",
        "nod": "Nod once, then hold still.",
    }
    return {"challenge": challenge, "prompt": prompts[challenge]}


def decode_and_normalize_frame(frame_b64: str, target_size=(224, 224)) -> np.ndarray:
    if "," in frame_b64:
        frame_b64 = frame_b64.split(",", 1)[1]

    frame_bytes = base64.b64decode(frame_b64)
    image = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
    image = image.resize(target_size)

    frame_array = np.asarray(image, dtype=np.float32)
    frame_array = (frame_array - 127.5) / 128.0
    return frame_array


def _preprocess_sequence(frames_b64: List[str], max_frames: int = 5) -> List[np.ndarray]:
    selected_frames = [frame for frame in frames_b64 if frame]
    if not selected_frames:
        raise ValueError("At least one frame is required for liveness analysis")

    selected_frames = selected_frames[-max_frames:]
    frame_batch = [decode_and_normalize_frame(frame) for frame in selected_frames]
    return frame_batch


def _load_cnn_model(model_path: Optional[str] = None):
    global _loaded_model
    if _loaded_model is not None:
        return _loaded_model

    effective_path = model_path or LIVENESS_MODEL_PATH
    if not TF_AVAILABLE or keras is None or not os.path.exists(effective_path):
        return None

    try:
        _loaded_model = keras.models.load_model(effective_path)
        return _loaded_model
    except Exception as exc:
        print(f"[Liveness] CNN model load skipped: {exc}")
        return None


def _stack_frames_for_motion(frame_list: List[np.ndarray]) -> np.ndarray:
    """Stack a list of frames into a single ndarray for motion analysis."""
    if not frame_list:
        return np.empty((0, 224, 224, 3), dtype=np.float32)
    return np.stack(frame_list, axis=0)


def _motion_series(frame_batch: np.ndarray) -> np.ndarray:
    if frame_batch.shape[0] < 2:
        return np.array([0.0], dtype=np.float32)

    diffs = np.abs(np.diff(frame_batch, axis=0))
    return diffs.mean(axis=(1, 2, 3))


def _band_motion(frame_batch: np.ndarray, band: slice) -> np.ndarray:
    if frame_batch.shape[0] < 2:
        return np.array([0.0], dtype=np.float32)

    diffs = np.abs(np.diff(frame_batch[:, band, :, :], axis=0))
    return diffs.mean(axis=(1, 2, 3))


def _left_right_asymmetry(frame_batch: np.ndarray) -> float:
    if frame_batch.shape[0] < 2:
        return 0.0

    diffs = np.abs(np.diff(frame_batch, axis=0))
    midpoint = frame_batch.shape[2] // 2
    left_motion = diffs[:, :, :midpoint, :].mean()
    right_motion = diffs[:, :, midpoint:, :].mean()
    return float(abs(left_motion - right_motion) / (left_motion + right_motion + 1e-6))


def _top_bottom_asymmetry(frame_batch: np.ndarray) -> float:
    if frame_batch.shape[0] < 2:
        return 0.0

    diffs = np.abs(np.diff(frame_batch, axis=0))
    midpoint = frame_batch.shape[1] // 2
    top_motion = diffs[:, :midpoint, :, :].mean()
    bottom_motion = diffs[:, midpoint:, :, :].mean()
    return float(abs(top_motion - bottom_motion) / (top_motion + bottom_motion + 1e-6))


def _passive_liveness_score(frame_batch: List[np.ndarray]) -> Dict[str, float]:
    frame_stack = _stack_frames_for_motion(frame_batch)
    motion_series = _motion_series(frame_stack)
    avg_motion = float(motion_series.mean())
    motion_variance = float(motion_series.std())
    uniformity = float(1.0 - min(1.0, motion_variance / (avg_motion + 1e-6)))
    motion_strength = float(min(1.0, avg_motion / 0.14))
    center_band = slice(frame_stack.shape[1] // 4, frame_stack.shape[1] * 3 // 4)
    edge_band = slice(0, frame_stack.shape[1] // 4)
    center_motion = float(_band_motion(frame_stack, center_band).mean())
    edge_motion = float(_band_motion(frame_stack, edge_band).mean()) if edge_band.stop > edge_band.start else center_motion
    center_focus = float(min(1.0, center_motion / (edge_motion + 1e-6)))

    score = 0.45 * motion_strength + 0.30 * (1.0 - uniformity) + 0.25 * center_focus
    return {
        "score": float(np.clip(score, 0.0, 1.0)),
        "motion_strength": motion_strength,
        "uniformity": uniformity,
        "center_focus": center_focus,
    }


def _active_challenge_score(frame_batch: List[np.ndarray], challenge: Optional[str]) -> Dict[str, float]:
    if not challenge:
        return {"score": 0.0, "challenge": 0.0, "asymmetry": 0.0}

    frame_stack = _stack_frames_for_motion(frame_batch)
    motion_series = _motion_series(frame_stack)
    peak = float(motion_series.max()) if motion_series.size else 0.0
    trough = float(motion_series.min()) if motion_series.size else 0.0
    peak_prominence = float((peak - trough) / (peak + 1e-6))

    if challenge == "blink":
        upper_band = slice(frame_stack.shape[1] // 2)
        lower_band = slice(frame_stack.shape[1] // 2, frame_stack.shape[1])
        upper_motion = float(_band_motion(frame_stack, upper_band).mean())
        lower_motion = float(_band_motion(frame_stack, lower_band).mean())
        band_balance = float(1.0 - min(1.0, abs(upper_motion - lower_motion) / (upper_motion + lower_motion + 1e-6)))
        score = 0.65 * peak_prominence + 0.35 * band_balance
        return {"score": float(np.clip(score, 0.0, 1.0)), "challenge": peak_prominence, "asymmetry": band_balance}

    if challenge in ("turn_left", "turn_right"):
        asymmetry = _left_right_asymmetry(frame_stack)
    elif challenge == "nod":
        asymmetry = _top_bottom_asymmetry(frame_stack)

    score = 0.65 * peak_prominence + 0.35 * asymmetry
    return {"score": float(np.clip(score, 0.0, 1.0)), "challenge": peak_prominence, "asymmetry": asymmetry}


def _cnn_liveness_score(frame_batch: List[np.ndarray], model_path: Optional[str] = None) -> Dict[str, float]:
    cnn_model = _load_cnn_model(model_path)
    if cnn_model is None:
        return {"score": 0.0, "real_prob": 0.0}

    predictions = []
    for frame in frame_batch:
        frame_expanded = np.expand_dims(frame, axis=0)
        prediction = cnn_model.predict(frame_expanded, verbose=0)
        predictions.append(float(prediction[0][0]))

    avg_prediction = np.mean(predictions) if predictions else 0.0

    return {
        "score": float(np.clip(avg_prediction, 0.0, 1.0)),
        "real_prob": float(np.clip(avg_prediction, 0.0, 1.0)),
    }


def analyze_liveness(
    frames_b64: List[str],
    challenge: Optional[str],
    threshold: float = 0.75,
    cnn_model_path: Optional[str] = None,
) -> Dict:
    if not frames_b64:
        return {"passed": False, "reason": "No frames provided"}

    try:
        frame_batch = _preprocess_sequence(frames_b64)
    except ValueError as e:
        return {"passed": False, "reason": str(e)}

    passive = _passive_liveness_score(frame_batch)
    active = _active_challenge_score(frame_batch, challenge)
    cnn = _cnn_liveness_score(frame_batch, model_path=cnn_model_path)

    if cnn is None:
        final_score = 0.65 * passive["score"] + 0.35 * active["score"]
        model_source = "heuristic"
    else:
        final_score = 0.50 * cnn + 0.30 * passive["score"] + 0.20 * active["score"]
        model_source = "cnn+heuristic"

    passed = final_score >= threshold and passive["score"] >= 0.45
    reasons = []
    if passive["score"] < 0.45:
        reasons.append("passive motion is too uniform")
    if challenge and active["score"] < 0.40:
        reasons.append(f"challenge response for {challenge} is weak")
    if cnn is not None and cnn < 0.40:
        reasons.append("CNN liveness confidence is low")

    return {
        "passed": passed,
        "score": float(np.clip(final_score, 0.0, 1.0)),
        "passive_score": passive["score"],
        "active_score": active["score"],
        "cnn_score": cnn,
        "model_source": model_source,
        "challenge": challenge,
        "reasons": reasons,
    }