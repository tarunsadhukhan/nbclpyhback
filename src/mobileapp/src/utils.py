import base64
import cv2
import numpy as np


def decode_image(base64_str):
    img_data = base64.b64decode(base64_str)
    np_arr   = np.frombuffer(img_data, np.uint8)
    img_bgr  = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    img_rgb  = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    return img_rgb
