from ultralytics import YOLO

if __name__ == '__main__':
    model = YOLO('yolo11s.pt')
    results = model.train(
        data=r'S:\Dev\Program\VIPER\VIPER-vx\laptop\backend\data\pipe_only\data.yaml',
        epochs=150,
        imgsz=640,
        batch=8,
        name='viper_pipe_v1',
        project=r'S:\Dev\Program\VIPER\VIPER-vx\laptop\backend\runs\detect',
        patience=30,
        device=0,
        optimizer='SGD',
        lr0=0.01,
        lrf=0.001,
        momentum=0.937,
        warmup_epochs=5,
        hsv_s=0.6,
        hsv_v=0.6,
        fliplr=0.5,
        flipud=0.3,
        mosaic=0.5,
        degrees=15.0,
        scale=0.3,
        cache='disk',
        workers=0,
        single_cls=True,
        box=10.0,
        cls=0.3,
    )
    print('Done! mAP50:', results.results_dict.get('metrics/mAP50(B)', 'N/A'))
