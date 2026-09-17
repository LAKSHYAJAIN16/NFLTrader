"""Grabs a single frame from a video source and saves it as a PNG, so you can
open it in an image viewer and measure pixel coordinates for data/roi.json.

Usage: python tools/save_sample_frame.py <video_path_or_url> [--time 30] [--out frame.png]
"""

import argparse
import sys

import cv2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", help="Video file path, RTSP/HTTP stream URL")
    parser.add_argument("--time", type=float, default=10.0, help="Seconds into the video to grab")
    parser.add_argument("--out", default="sample_frame.png")
    args = parser.parse_args()

    cap = cv2.VideoCapture(args.source)
    if not cap.isOpened():
        sys.exit(f"Could not open source: {args.source}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(fps * args.time))
    ok, frame = cap.read()
    cap.release()

    if not ok:
        sys.exit("Could not read a frame at that timestamp.")

    cv2.imwrite(args.out, frame)
    print(f"Saved {args.out} ({frame.shape[1]}x{frame.shape[0]}). "
          f"Open it in an image viewer to measure ROI pixel coordinates.")


if __name__ == "__main__":
    main()
