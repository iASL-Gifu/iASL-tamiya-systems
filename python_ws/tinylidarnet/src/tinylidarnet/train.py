"""教師あり模倣学習。実行時だけNumPyとPyTorchを読み込む。"""

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import random


def main():
    parser = argparse.ArgumentParser(description='TinyLidarNetの操舵・スロットルを学習します')
    parser.add_argument('--train', nargs='+', required=True, help='学習用NPZ')
    parser.add_argument('--val', nargs='+', required=True, help='別走行で収録した検証用NPZ')
    parser.add_argument('--output', type=Path, help='出力先を直接指定する場合のみ使用')
    parser.add_argument('--output-root', type=Path,
                        default=Path(__file__).resolve().parents[2] / 'outputs',
                        help='日時別出力の親ディレクトリ（初期値: パッケージ直下のoutputs）')
    parser.add_argument('--epochs', type=int, default=20)
    parser.add_argument('--batch-size', type=int, default=64)
    parser.add_argument('--learning-rate', type=float, default=5e-5)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--device', default='auto', help='auto / cpu / cuda / cuda:0 / mps')
    args = parser.parse_args()
    started_at = datetime.now().astimezone()
    if args.epochs <= 0 or args.batch_size <= 0:
        parser.error('epochsとbatch-sizeは正の整数にしてください')
    if not math.isfinite(args.learning_rate) or args.learning_rate <= 0:
        parser.error('learning-rateは有限の正の値にしてください')
    if not 0 <= args.seed < 2**32:
        parser.error('seedは0以上2**32未満にしてください')
    if args.output is not None and args.output.expanduser().exists():
        parser.error('outputには既存のデータを上書きしないよう、新しいディレクトリを指定してください')

    import numpy as np
    import torch
    from torch.utils.data import DataLoader, TensorDataset
    from tqdm.auto import tqdm

    from .dataset import load_sessions
    from .devices import resolve_device
    from .model import TinyLidarNet
    from .run_paths import create_run_directory
    from .spec import metadata

    device = resolve_device(torch, args.device)
    tqdm.write(f'学習デバイス: {device}')
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    train_x, train_y, config, train_ids = load_sessions(args.train)
    val_x, val_y, val_config, val_ids = load_sessions(args.val)
    if train_ids & val_ids:
        raise ValueError('学習用と検証用に同じ収録セッションが含まれています')
    if config != val_config:
        raise ValueError('学習用と検証用の前処理設定が異なります')
    model = TinyLidarNet(config.sample_count).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate)
    criterion = torch.nn.HuberLoss()

    def loader(scans, targets, shuffle):
        dataset = TensorDataset(torch.from_numpy(scans).unsqueeze(1), torch.from_numpy(targets))
        return DataLoader(dataset, batch_size=args.batch_size, shuffle=shuffle, num_workers=0)

    training = loader(train_x, train_y, True)
    validation = loader(val_x, val_y, False)
    if args.output is None:
        args.output = create_run_directory(args.output_root, started_at)
    else:
        args.output = args.output.expanduser()
        args.output.mkdir(parents=True, exist_ok=False)
    tqdm.write(f'出力先: {args.output.resolve()}')
    history = []
    best_loss = math.inf
    best_epoch = None
    for epoch in tqdm(range(1, args.epochs + 1), desc='Epoch', unit='epoch'):
        model.train()
        train_loss = 0.0
        training_progress = tqdm(training, desc=f'Train {epoch}/{args.epochs}', unit='batch', leave=False)
        for scans, targets in training_progress:
            scans, targets = scans.to(device), targets.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(scans), targets)
            if not torch.isfinite(loss):
                raise ValueError('学習損失が非有限値になりました')
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * len(scans)
            training_progress.set_postfix(loss=f'{loss.item():.6f}')

        model.eval()
        val_loss = 0.0
        absolute_error = torch.zeros(2, device=device)
        with torch.inference_mode():
            for scans, targets in tqdm(validation, desc=f'Val {epoch}/{args.epochs}', unit='batch', leave=False):
                scans, targets = scans.to(device), targets.to(device)
                predictions = model(scans)
                loss = criterion(predictions, targets)
                if not torch.isfinite(loss):
                    raise ValueError('検証損失が非有限値になりました')
                val_loss += loss.item() * len(scans)
                absolute_error += (predictions - targets).abs().sum(dim=0)
        val_loss /= len(val_x)
        errors = (absolute_error / len(val_x)).cpu().tolist()
        record = {
            'epoch': epoch, 'train_loss': train_loss / len(train_x), 'val_loss': val_loss,
            'val_steering_mae': errors[0], 'val_throttle_mae': errors[1],
        }
        history.append(record)
        tqdm.write(json.dumps(record))
        if val_loss < best_loss:
            best_loss, best_epoch = val_loss, epoch
            torch.save({name: tensor.detach().cpu() for name, tensor in model.state_dict().items()},
                       args.output / 'weights.pt')
        (args.output / 'history.json').write_text(json.dumps(history, indent=2) + '\n')

    info = metadata(config)
    info['training'] = {
        'started_at': started_at.isoformat(),
        'device': str(device),
        'epochs': args.epochs, 'batch_size': args.batch_size, 'learning_rate': args.learning_rate,
        'seed': args.seed, 'best_epoch': best_epoch, 'best_val_loss': best_loss,
        'train_samples': len(train_x), 'val_samples': len(val_x),
        'train_sessions': sorted(train_ids), 'val_sessions': sorted(val_ids),
        'torch_version': str(torch.__version__),
    }
    (args.output / 'metadata.json').write_text(json.dumps(info, indent=2) + '\n')
    print(f'モデルを保存しました: {args.output.resolve()}')


if __name__ == '__main__':
    main()
