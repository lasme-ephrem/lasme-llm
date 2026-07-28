from scripts.evaluate_models import response_metrics, summarize_model


def test_response_metrics_uses_native_ollama_timings() -> None:
    metrics = response_metrics(
        {
            "message": {"content": "Réponse correcte."},
            "prompt_eval_count": 120,
            "eval_count": 80,
            "load_duration": 500_000_000,
            "prompt_eval_duration": 1_000_000_000,
            "eval_duration": 2_000_000_000,
            "done_reason": "stop",
        },
        wall_seconds=4.25,
    )
    assert metrics["tokens_per_second"] == 40.0
    assert metrics["load_seconds"] == 0.5
    assert metrics["prompt_tokens"] == 120
    assert metrics["output_tokens"] == 80
    assert metrics["valid_answer"] is True


def test_model_summary_is_weighted_by_generation_duration() -> None:
    summary = summarize_model(
        [
            {
                "output_tokens": 100,
                "generation_seconds": 2.0,
                "tokens_per_second": 50.0,
                "wall_seconds": 3.0,
                "load_seconds": 0.5,
                "valid_answer": True,
            },
            {
                "output_tokens": 60,
                "generation_seconds": 1.0,
                "tokens_per_second": 60.0,
                "wall_seconds": 2.0,
                "load_seconds": 0.0,
                "valid_answer": True,
            },
        ]
    )
    assert summary["weighted_tokens_per_second"] == 53.33
    assert summary["median_tokens_per_second"] == 55.0
    assert summary["valid_answers"] == 2
