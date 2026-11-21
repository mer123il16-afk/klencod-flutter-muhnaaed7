#!/usr/bin/env python3
"""رفع جودة فيديو حقيقي بشبكة عصبية (OpenCV dnn_superres) + ffmpeg.
تشغيل:  python upscale.py input.mp4 [-m fsrcnn|espcn|edsr] [-s 2|3|4] [-o out.mp4]
Termux:  pkg install python ffmpeg opencv-python  (أو pip install opencv-contrib-python-headless numpy)
الصوت يُنسخ من الفيديو الأصلي. الموديلات تنزل مرة وحدة وتنحفظ جنب السكربت.
"""
import argparse, os, subprocess, sys, urllib.request
import cv2, numpy as np

BASE = {
    "fsrcnn": "https://github.com/Saafke/FSRCNN_Tensorflow/raw/master/models/FSRCNN_x%d.pb",
    "espcn": "https://github.com/fannymonori/TF-ESPCN/raw/master/export/ESPCN_x%d.pb",
    "edsr": "https://github.com/Saafke/EDSR_Tensorflow/raw/master/models/EDSR_x%d.pb",
}
HERE = os.path.dirname(os.path.abspath(__file__))


def load(model, scale):
    path = os.path.join(HERE, f"{model}_x{scale}.pb")
    if not os.path.exists(path):
        url = BASE[model] % scale
        print("تنزيل الموديل:", url)
        urllib.request.urlretrieve(url, path)
    sr = cv2.dnn_superres.DnnSuperResImpl_create()
    sr.readModel(path)
    sr.setModel(model, scale)
    return sr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("-m", "--model", default="fsrcnn", choices=BASE)
    ap.add_argument("-s", "--scale", type=int, default=2)
    ap.add_argument("-o", "--out")
    ap.add_argument("--bicubic", action="store_true", help="للاختبار فقط (بدون شبكة)")
    a = ap.parse_args()
    out = a.out or os.path.splitext(a.inp)[0] + f"_x{a.scale}.mp4"

    cap = cv2.VideoCapture(a.inp)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    w, h = int(cap.get(3)), int(cap.get(4))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    sr = None if a.bicubic else load(a.model, a.scale)
    W, H = w * a.scale, h * a.scale
    tmp = out + ".noaudio.mp4"
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
         "-r", str(fps), "-i", "-", "-c:v", "libx264", "-crf", "16", "-preset", "medium",
         "-pix_fmt", "yuv420p", tmp], stdin=subprocess.PIPE)
    i = 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        r = cv2.resize(f, (W, H), interpolation=cv2.INTER_CUBIC) if sr is None else sr.upsample(f)
        enc.stdin.write(np.ascontiguousarray(r).tobytes())
        i += 1
        print(f"\rإطار {i}/{n}", end="", flush=True)
    enc.stdin.close(); enc.wait()
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", tmp, "-i", a.inp, "-map", "0:v", "-map", "1:a?",
                    "-c", "copy", "-shortest", out])
    os.remove(tmp)
    print("\nتم:", out)


if __name__ == "__main__":
    main()
