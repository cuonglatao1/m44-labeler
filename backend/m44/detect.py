"""2D side: YOLO detections on the 6 camera images."""

# COCO class id -> name, only classes that have a nuScenes counterpart
COCO_CLASSES = {0: 'person', 1: 'bicycle', 2: 'car', 3: 'motorcycle', 5: 'bus', 7: 'truck'}


def detect(frames: list[dict], weights: str = 'yolo11m.pt', conf: float = 0.25,
           imgsz: int = 1280, device: str | int = 'auto') -> list[dict]:
    import torch
    from ultralytics import YOLO

    if device == 'auto':
        device = 0 if torch.cuda.is_available() else 'cpu'
    model = YOLO(weights)
    out = []
    for frame in frames:
        for cam_name, cam in frame['cams'].items():
            r = model.predict(cam['img_path'], conf=conf, imgsz=imgsz, device=device,
                              classes=list(COCO_CLASSES), verbose=False)[0]
            for xyxy, cls, score in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist()):
                out.append({'sample': frame['sample'], 'cam': cam_name, 'cls': COCO_CLASSES[int(cls)],
                            'bbox': [float(v) for v in xyxy], 'score': float(score)})
    return out
