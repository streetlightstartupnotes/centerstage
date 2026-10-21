import argparse
import os

import cv2


def main():
    parser = argparse.ArgumentParser(description="Save evenly spaced frames from a local video.")
    parser.add_argument("video")
    parser.add_argument("--output", default="member_identification_frames")
    parser.add_argument("--count", type=int, default=10)
    args = parser.parse_args()
    os.makedirs(args.output, exist_ok=True)
    capture = cv2.VideoCapture(args.video)
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = capture.get(cv2.CAP_PROP_FPS) or 1
    print(f"frames={total} fps={fps:.2f} duration={total / fps:.1f}s")
    saved = 0
    for index, frame_index in enumerate(int(total * i / (args.count + 1)) for i in range(1, args.count + 1)):
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok:
            continue
        path = os.path.join(args.output, f"frame_{index:03d}_t{frame_index / fps:.1f}s.jpg")
        cv2.imwrite(path, frame)
        saved += 1
        print(path)
    capture.release()
    print(f"saved {saved}")


if __name__ == "__main__":
    main()
