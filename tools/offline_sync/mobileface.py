"""MobileFaceNet embedding helper — the server-side twin of the Android FaceEngine.

THE ALIGNMENT CONTRACT
----------------------
Both sides MUST do exactly this, or the vectors are not comparable:

  1. locate the face; take the two eye centres
  2. rotate the image so the eye line is horizontal
  3. crop the (rotated) face box with a 20% margin on every side
  4. resize to 112x112 RGB
  5. scale pixels to [-1, 1] with (px - 127.5) / 128.0
  6. run the model, take the 192-d output, L2-normalise it

Anything that changes here changes MOBILE_MODEL_VER in src/sync/routes.py and
forces a re-embed of every enrolment photo plus a re-pull on every device.

Model file: tools/models/mobilefacenet.onnx (server) and
app/src/main/assets/mobilefacenet.tflite (device) — the SAME weights, exported
twice. Neither binary is in git; drop them in before running.
"""
import os

import numpy as np

INPUT_SIZE = 112
CROP_MARGIN = 0.20
EMBEDDING_DIM = 192
MODEL_VER = 'mobilefacenet-v1'

_DEFAULT_MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'models', 'mobilefacenet.onnx')


class MobileFaceEmbedder:
    """Loads mobilefacenet once and embeds aligned 112x112 crops."""

    def __init__(self, model_path=None):
        self.model_path = model_path or os.environ.get('MOBILEFACENET_MODEL', _DEFAULT_MODEL)
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"MobileFaceNet model not found at {self.model_path}.\n"
                "Download/export the weights first, e.g. an ONNX export of "
                "MobileFaceNet, and place it there (or set MOBILEFACENET_MODEL).")
        self._kind = 'onnx' if self.model_path.endswith('.onnx') else 'tflite'
        if self._kind == 'onnx':
            import onnxruntime
            self._sess = onnxruntime.InferenceSession(
                self.model_path, providers=['CPUExecutionProvider'])
            self._input = self._sess.get_inputs()[0]
            # NCHW (1,3,112,112) or NHWC (1,112,112,3) — detect from the shape.
            self._nchw = list(self._input.shape)[1] == 3
        else:
            try:
                from tflite_runtime.interpreter import Interpreter
            except ImportError:
                from tensorflow.lite.python.interpreter import Interpreter
            self._interp = Interpreter(model_path=self.model_path)
            self._interp.allocate_tensors()
            self._in = self._interp.get_input_details()[0]
            self._out = self._interp.get_output_details()[0]
            self._nchw = list(self._in['shape'])[1] == 3

    def embed(self, crop_rgb):
        """[112,112,3] uint8 RGB -> L2-normalised float32 vector."""
        x = (crop_rgb.astype(np.float32) - 127.5) / 128.0
        x = np.transpose(x, (2, 0, 1)) if self._nchw else x
        x = np.expand_dims(x, 0)
        if self._kind == 'onnx':
            vec = self._sess.run(None, {self._input.name: x})[0][0]
        else:
            self._interp.set_tensor(self._in['index'], x)
            self._interp.invoke()
            vec = self._interp.get_tensor(self._out['index'])[0]
        vec = np.asarray(vec, dtype=np.float32).reshape(-1)
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec


def align_face(image_rgb, landmarks, box):
    """Rotate on the eye line, crop with a margin, resize to 112x112.

    image_rgb : HxWx3 uint8
    landmarks : dict from face_recognition.face_landmarks() (needs the eyes)
    box       : (top, right, bottom, left) from face_recognition.face_locations()
    """
    from PIL import Image

    left_eye = np.mean(landmarks['left_eye'], axis=0)
    right_eye = np.mean(landmarks['right_eye'], axis=0)
    dy, dx = right_eye[1] - left_eye[1], right_eye[0] - left_eye[0]
    angle_deg = float(np.degrees(np.arctan2(dy, dx)))

    top, right, bottom, left = box
    cx, cy = (left + right) / 2.0, (top + bottom) / 2.0

    img = Image.fromarray(image_rgb)
    # PIL rotates counter-clockwise for positive angles; rotate about the face
    # centre so the crop box below stays valid.
    img = img.rotate(angle_deg, resample=Image.BILINEAR, center=(cx, cy))

    half_w = (right - left) * (0.5 + CROP_MARGIN)
    half_h = (bottom - top) * (0.5 + CROP_MARGIN)
    crop = img.crop((int(cx - half_w), int(cy - half_h),
                     int(cx + half_w), int(cy + half_h)))
    crop = crop.resize((INPUT_SIZE, INPUT_SIZE), Image.BILINEAR)
    return np.asarray(crop.convert('RGB'), dtype=np.uint8)


def embed_image_bytes(embedder, image_bytes):
    """JPEG/PNG bytes -> (vector, reason). vector is None when no usable face."""
    import io

    import face_recognition
    from PIL import Image

    image = np.asarray(Image.open(io.BytesIO(image_bytes)).convert('RGB'), dtype=np.uint8)
    boxes = face_recognition.face_locations(image)
    if not boxes:
        return None, 'no_face'
    # Largest face wins, same rule the device uses.
    box = max(boxes, key=lambda b: (b[2] - b[0]) * (b[1] - b[3]))
    marks = face_recognition.face_landmarks(image, [box])
    if not marks or 'left_eye' not in marks[0] or 'right_eye' not in marks[0]:
        return None, 'no_landmarks'
    return embedder.embed(align_face(image, marks[0], box)), 'ok'


def cosine(a, b):
    return float(np.dot(a, b))  # inputs are already L2-normalised


def _self_check():
    """Alignment maths only — runs without the model or face_recognition."""
    from PIL import Image

    img = np.zeros((200, 200, 3), dtype=np.uint8)
    img[80:120, 60:140] = 255
    marks = {'left_eye': [(80, 100), (84, 100)], 'right_eye': [(120, 108), (124, 108)]}
    out = align_face(img, marks, (70, 140, 130, 60))
    assert out.shape == (INPUT_SIZE, INPUT_SIZE, 3), out.shape
    assert out.dtype == np.uint8

    v = np.array([3.0, 4.0], dtype=np.float32)
    v = v / np.linalg.norm(v)
    assert abs(cosine(v, v) - 1.0) < 1e-6
    assert abs(np.linalg.norm(v) - 1.0) < 1e-6
    # A 20% margin makes the crop 1.4x the box on each axis.
    assert abs((0.5 + CROP_MARGIN) * 2 - 1.4) < 1e-9
    print('mobileface self-check OK')


if __name__ == '__main__':
    _self_check()
