"""재현 가능한 고정 시점 1년 예측: python src/models/run_forecast.py.

2021~2023 -> 2024 검증으로 설정 선택, 2021~2024 재학습 -> 2025 테스트.
원자료 결측은 보존. 공통 관측일 평가와 모델별 전체 관측일 평가를 구분한다.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import ROOT_DIR, RAW_TEMP_DIR, REGION_FOLDER_MAP, REGIONS
from data.load_data import load_raw_temperature
from models.forecast import (evaluate, naive_seasonal_forecast, moving_average_forecast,
                             climatology_forecast)
from models.harmonic import HarmonicRegression

SLUGS = dict(zip(REGIONS, ['wando', 'yeosu', 'tongyeong', 'namhae']))
MODEL_COLORS = {'climatology': '#2a78d6', 'naive_seasonal': '#898781',
                'moving_average': '#c9c6bd', 'harmonic_regression': '#1baf7a'}


def gap_table(series, region):
    missing = series.isna()
    groups = missing.ne(missing.shift()).cumsum()
    return [dict(region=region, start=g.index.min(), end=g.index.max(), days=len(g))
            for _, g in series[missing].groupby(groups[missing])]


def audit_raw(region, raw_dir):
    frames = []
    for file in sorted((raw_dir / REGION_FOLDER_MAP[region]).glob('*.csv')):
        frame = pd.read_csv(file, encoding='utf-8-sig')
        frame['source_file'] = file.name
        frames.append(frame)
    if not frames:
        raise FileNotFoundError(f'{region}: 원자료가 없습니다.')
    raw = pd.concat(frames, ignore_index=True)
    duplicate = raw[raw.duplicated('obsrvnDt', keep=False)].copy()
    duplicate['region'] = region
    duplicate['conflicting_temperature'] = duplicate.groupby('obsrvnDt')['wtemS'].transform(
        lambda s: s.nunique(dropna=False) > 1)
    return duplicate[['region', 'obsrvnDt', 'wtemS', 'source_file', 'conflicting_temperature']]


def select_settings(series):
    # 호출부가 2025년 이전 자료만 전달하므로 테스트 수온을 참조하지 않는다.
    train, valid = series.loc['2021':'2023'], series.loc['2024']
    observed = np.isfinite(valid.to_numpy())
    if not observed.any():
        raise ValueError('2024년 검증 관측값이 없습니다.')
    rows = []
    for harmonics in (1, 2, 3, 4, 6):
        for trend in (False, True):
            model = HarmonicRegression(harmonics, trend).fit(train.index, train)
            pred = model.predict(valid.index)
            error = valid.to_numpy()[observed] - pred[observed]
            rows.append(dict(harmonics=harmonics, trend=trend, n_scored=int(observed.sum()),
                             MAE=float(np.mean(np.abs(error))), RMSE=float(np.sqrt(np.mean(error**2)))))
    table = pd.DataFrame(rows).sort_values(['RMSE', 'harmonics', 'trend']).reset_index(drop=True)
    chosen = table.iloc[0]
    return dict(harmonics=int(chosen.harmonics), trend=bool(chosen.trend)), table


def fit_predict(series):
    train, test = series.loc['2021':'2024'], series.loc['2025']
    settings, validation = select_settings(train)
    harmonic = HarmonicRegression(**settings).fit(train.index, train)
    train_df = train.rename('temperature').rename_axis('date').reset_index()
    test_df = test.rename('temperature').rename_axis('date').reset_index()
    predictions = {
        'climatology': climatology_forecast(train_df, test_df, window=3),
        'naive_seasonal': naive_seasonal_forecast(train_df, test_df),
        'moving_average': moving_average_forecast(train_df, len(test), window=7),
        'harmonic_regression': harmonic.predict(test.index),
    }
    return test, predictions, settings, validation


def run(regions, raw_dir=RAW_TEMP_DIR, output=None):
    output = Path(output or ROOT_DIR / 'reports' / 'forecast_2025')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'figures').mkdir(exist_ok=True)
    metrics, predictions, validations, gaps, audits, duplicates, monthly = [], [], [], [], [], [], []
    selections = {}
    for region in regions:
        duplicates.append(audit_raw(region, raw_dir))
        raw = load_raw_temperature(region, raw_dir).set_index('date').temperature
        series = raw.reindex(pd.date_range('2021-01-01', '2025-12-31', freq='D'))
        if np.isinf(series.to_numpy(dtype=float)).any():
            raise ValueError(f'{region}: 무한대 수온을 확인하세요.')
        gaps.extend(gap_table(series, region))
        for label, start, end in [('training', '2021', '2024'), ('test', '2025', '2025')]:
            part = series.loc[start:end]
            gg = gap_table(part, region)
            audits.append(dict(region=region, split=label, n_days=len(part),
                               n_observed=int(part.notna().sum()), n_missing=int(part.isna().sum()),
                               max_gap_days=max([g['days'] for g in gg], default=0),
                               n_outside_period=int((~raw.index.isin(series.index)).sum())))
        test, preds, settings, validation = fit_predict(series)
        selections[region] = settings
        validations.append(validation.assign(region=region))
        actual = test.to_numpy(dtype=float)
        common = np.isfinite(actual) & np.logical_and.reduce([np.isfinite(v) for v in preds.values()])
        for name, pred in preds.items():
            available = np.isfinite(actual) & np.isfinite(pred)
            for scope, mask in [('common_dates', common), ('available_dates', available)]:
                if not mask.any():
                    raise ValueError(f'{region}/{name}: 평가할 관측값이 없습니다.')
                metrics.append(dict(region=region, model=name, scope=scope,
                                    n_scored=int(mask.sum()), n_observed=int(np.isfinite(actual).sum()),
                                    n_predicted=int(np.isfinite(pred).sum()), **evaluate(actual[mask], pred[mask])))
            rows = pd.DataFrame(dict(date=test.index, region=region, model=name, actual=actual,
                                     prediction=pred, actual_observed=np.isfinite(actual),
                                     scored_common=common, scored_available=available,
                                     forecast_origin='2024-12-31'))
            predictions.append(rows)
            for month in range(1, 13):
                mask = common & (test.index.month == month)
                monthly.append(dict(region=region, model=name, month=month, n_scored=int(mask.sum()),
                                    **(evaluate(actual[mask], pred[mask]) if mask.any() else {'MAE':np.nan, 'RMSE':np.nan})))
        plot_region(region, test, preds, output)
    metric_df = pd.DataFrame(metrics)
    products = {'metrics.csv': metric_df, 'predictions.csv': pd.concat(predictions),
                'validation_metrics.csv': pd.concat(validations),
                'missing_runs.csv': pd.DataFrame(gaps, columns=['region','start','end','days']),
                'data_quality.csv': pd.DataFrame(audits), 'duplicate_dates.csv': pd.concat(duplicates),
                'monthly_metrics.csv': pd.DataFrame(monthly)}
    for name, table in products.items():
        table.to_csv(output / name, index=False, encoding='utf-8-sig')
    common_df = metric_df.query("scope == 'common_dates'")
    comparison = common_df.pivot(index='region', columns='model', values=['MAE','RMSE'])
    comparison.columns = ['_'.join(c) for c in comparison.columns]
    comparison['RMSE_improvement_pct'] = 100 * (1 - comparison.RMSE_climatology / comparison.RMSE_naive_seasonal)
    comparison.to_csv(output / 'model_comparison.csv', encoding='utf-8-sig')
    plot_comparison(common_df, output)
    inputs = {str(p.relative_to(raw_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
              for region in regions for p in sorted((raw_dir / REGION_FOLDER_MAP[region]).glob('*.csv'))}
    metadata = dict(upstream_commit='eb32630eea425efe538c962f7878aa2108f248d2',
                    forecast_origin='2024-12-31', test_period=['2025-01-01','2025-12-31'],
                    validation='train 2021-2023 / validate 2024; then refit 2021-2024',
                    selection_metric='2024 RMSE; ties prefer fewer harmonics, no trend',
                    selected_settings=selections, missing_policy='no imputation; fit observed; evaluate observed',
                    duplicate_policy='sorted file names, keep first (upstream convention); report conflicts',
                    python=platform.python_version(), versions={n:importlib.metadata.version(n) for n in
                    ['pandas','numpy','scikit-learn','matplotlib']}, input_sha256=inputs)
    (output / 'run_metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print(common_df.to_string(index=False))
    print(f'저장 완료: {output}')
    return metric_df


def plot_region(region, actual, preds, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(12, 4.8))
    ax.plot(actual.index, actual, color='#222222', lw=1.3, label='Observed (gaps preserved)')
    for name, pred in preds.items():
        ax.plot(actual.index, pred, label=name.replace('_',' '), color=MODEL_COLORS.get(name), lw=1.1,
                alpha=0.9, linestyle='--' if name=='moving_average' else '-')
    ax.set(title=f'{SLUGS[region].title()} | 2025 forecast made on 2024-12-31', ylabel='Surface temperature (°C)', xlabel='Date')
    ax.grid(alpha=.18); ax.legend(loc='upper left', ncol=2, fontsize=8)
    fig.tight_layout(); fig.savefig(output / 'figures' / f'{SLUGS[region]}_forecast.png', dpi=160); plt.close(fig)


def plot_comparison(metrics, output):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    for ax, score in zip(axes, ['MAE','RMSE']):
        table = metrics.pivot(index='region', columns='model', values=score).rename(index=SLUGS)
        table.plot.bar(ax=ax, color=[MODEL_COLORS.get(c) for c in table.columns], rot=0)
        ax.set(title=f'{score} on common observed dates', ylabel='Error (°C)', xlabel='Region')
        ax.grid(axis='y',alpha=.18)
        ax.get_legend().remove()
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', ncol=3)
    fig.tight_layout(rect=(0,.09,1,1)); fig.savefig(output / 'figures' / 'model_comparison.png', dpi=160); plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--regions', nargs='+', choices=REGIONS, default=REGIONS)
    parser.add_argument('--raw-dir', type=Path, default=RAW_TEMP_DIR)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    run(args.regions, args.raw_dir, args.output)
