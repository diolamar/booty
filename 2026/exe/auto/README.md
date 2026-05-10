# Video Object Detection

This folder contains a simple Python starter that can identify objects in:

- a saved video file
- a webcam stream

## Files

- `video_object_detector.py` - main script
- `requirements.txt` - Python packages to install

## Setup

```powershell
cd 2026\exe\auto
pip install -r requirements.txt
```

## Run with webcam

```powershell
python video_object_detector.py --source 0 --show
```

## Run with a video file

```powershell
python video_object_detector.py --source sample.mp4 --show --save --output detected.mp4
```

## Detect only specific objects

```powershell
python video_object_detector.py --source sample.mp4 --show --classes person car dog
```

## Notes

- Press `Esc` to close the preview window.
- The first run may download the default YOLO model automatically.
- Default model: `yolov8n.pt`
