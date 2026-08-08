#!/usr/bin/env python3
"""Treina ensemble, avalia holdout 30% e gera PDF de metricas + receita."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fpt.client import DATA
from fpt.models.evaluate import evaluate_holdout, save_evaluation
from fpt.models.train import train_models
from fpt.pipeline import load_merged
from fpt.report.pdf_model_eval import generate_model_eval_pdf
from fpt.integrations.google_drive import upload_file
from fpt.weekend import weekend_report_dir
from fpt.calendar import weekend_window


def main(retrain: bool = True):
    df = load_merged()
    print(f"Base: {len(df)} partidas")

    if retrain:
        print("\n=== Treinando ensemble ===")
        meta = train_models(df)
    else:
        import json
        meta = json.loads((DATA / "models" / "meta.json").read_text(encoding="utf-8"))

    print("\n=== Avaliando holdout 30% ===")
    result = evaluate_holdout(df)
    save_evaluation(result)

    start, _ = weekend_window()
    out_dir = weekend_report_dir(start)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_pdf = out_dir / f"ModeloEval_{start}.pdf"
    generate_model_eval_pdf(result, out_pdf, meta=meta)

    print(f"\nTrades holdout: {len(result.trades)} | Entradas modelo: {result.metrics.get('n_trades_model', 0)}")
    upload_file(out_pdf, history_date=str(start))
    return out_pdf


if __name__ == "__main__":
    retrain = "--no-train" not in sys.argv
    main(retrain=retrain)
