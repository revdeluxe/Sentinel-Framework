# Liveness Pipeline

## Goal
Combine face recognition with live-feed liveness detection while keeping the backend lean enough for edge deployment.

## Final Architecture
1. Browser camera capture collects a short burst of frames instead of a single still image.
2. The browser also receives a short randomized challenge such as blink, turn left, turn right, or nod.
3. The backend runs liveness analysis first.
4. If liveness passes, the backend extracts the face embedding and performs vector matching.
5. If the matched user is privileged, FaceID is blocked and password plus admin key is required.

## Liveness Layers
### Passive liveness
Passive liveness looks for motion patterns across the frame burst.

Signals used:
- Frame-to-frame motion energy
- Motion uniformity across the burst
- Center-weighted motion versus edge motion
- Left/right or top/bottom asymmetry

This is designed to reject replay attacks, static photos, and monitor captures without needing OpenCV or MediaPipe.

### Active liveness
Active liveness uses a challenge-response prompt.

Challenges used:
- Blink
- Turn left
- Turn right
- Nod

The implementation is intentionally lightweight:
- The browser shows the prompt
- The browser sends a burst of frames
- The backend checks whether the motion pattern matches the prompt

In a production build, the active layer can be replaced or strengthened with facial landmarks if a dedicated landmarks model is available.

## CNN Model Selection
Recommended options for edge inference:
- MobileNetV3 Small
- EfficientNet-Lite0

Selection criteria:
- Low latency on CPU
- Small model size
- Good transfer-learning support
- Easy deployment to browser-adjacent or backend edge environments

Recommended runtime strategy:
- Use a lightweight CNN spoof classifier when a trained model file exists
- Fall back to heuristic motion scoring when the CNN is absent
- Keep TensorFlow optional so compilation and startup remain fast

## Runtime Behavior
The current code path is deliberately lean:
- No OpenCV dependency
- No MediaPipe dependency
- Optional TensorFlow only if a trained CNN is present
- Heuristic fallback always available

## Training Notes
To train the CNN properly:
- Gather real and spoof examples across phones, screens, printed photos, and synthetic AI images
- Label at least real, photo spoof, screen replay, and print spoof
- Train on short frame sequences rather than single frames
- Validate against unseen devices and lighting conditions
- Calibrate thresholds per deployment

## Security Notes
- Face recognition alone should not unlock privileged admin sessions
- Privileged accounts must use password plus admin key
- Liveness failures should be logged and rate-limited
- Audit logs should record replay and liveness blocks
