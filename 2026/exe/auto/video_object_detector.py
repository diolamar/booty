import argparse
import os
from pathlib import Path

import cv2

APP_DIR = Path(__file__).resolve().parent
os.environ.setdefault("YOLO_CONFIG_DIR", str(APP_DIR / ".yolo_config"))

try:
    from ultralytics import YOLO
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: ultralytics\n"
        "Install requirements first:\n"
        "pip install -r requirements.txt"
    ) from exc


def parse_args():
    parser = argparse.ArgumentParser(
        description="Detect objects in a video file or webcam stream."
    )
    parser.add_argument(
        "--source",
        default="0",
        help='Video file path or camera index. Use "0" for default webcam.',
    )
    parser.add_argument(
        "--model",
        default="yolov8n.pt",
        help="YOLO model file or model name. Default: yolov8n.pt",
    )
    parser.add_argument(
        "--output",
        default="output_detected.mp4",
        help="Output video path when saving detections.",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save the annotated result to a video file.",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.25,
        help="Confidence threshold. Default: 0.25",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Show the live detection window.",
    )
    parser.add_argument(
        "--classes",
        nargs="*",
        default=None,
        help="Optional class names to keep, for example: person car dog",
    )
    return parser.parse_args()


def open_source(source_value):
    source = int(source_value) if source_value.isdigit() else source_value
    capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        raise SystemExit(f"Could not open source: {source_value}")
    return capture


def resolve_writer(capture, output_path):
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
    fps = capture.get(cv2.CAP_PROP_FPS)
    fps = fps if fps and fps > 0 else 20.0

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_file), fourcc, fps, (width, height))
    if not writer.isOpened():
        raise SystemExit(f"Could not create output video: {output_file}")
    return writer


def resolve_class_ids(model, requested_classes):
    if not requested_classes:
        return None

    requested = set(requested_classes)
    allowed_ids = [
        class_id for class_id, name in model.names.items() if name in requested
    ]
    return allowed_ids or None


def main():
    args = parse_args()
    capture = open_source(args.source)
    model = YOLO(args.model)
    class_ids = resolve_class_ids(model, args.classes)

    writer = resolve_writer(capture, args.output) if args.save else None

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break

            result = model(frame, conf=args.conf, classes=class_ids, verbose=False)[0]
            annotated = result.plot()

            if writer:
                writer.write(annotated)

            if args.show:
                cv2.imshow("Object Detection", annotated)
                if cv2.waitKey(1) & 0xFF == 27:
                    break
    finally:
        capture.release()
        if writer:
            writer.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
