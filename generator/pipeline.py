"""End-to-end pipeline for template-only UAV dataset generation."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from generator.config_linter import assert_valid_config
from generator.template_generator import GENERATOR_VERSION, GeneratorConfig, generate_samples, load_configs
from generator.validator import ValidationResult, save_validation_outputs, validate_samples


PIPELINE_VERSION = "0.1.0"


@dataclass(frozen=True)
class PipelineConfig:
    """Runtime configuration for the generation pipeline."""

    sample_count: int = 100
    seed: int = 42
    val_ratio: float = 0.2
    config_dir: Path = Path("config")
    raw_dir: Path = Path("raw")
    processed_dir: Path = Path("processed")
    stats_dir: Path = Path("stats")
    fail_on_invalid: bool = False


@dataclass(frozen=True)
class PipelineResult:
    """Summary of one pipeline run."""

    generated_count: int
    valid_count: int
    invalid_count: int
    deduplicated_count: int
    duplicate_count: int
    train_count: int
    val_count: int
    distribution_report: dict[str, Any]
    validation_report: dict[str, Any]
    pipeline_report: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PipelineError(RuntimeError):
    """Raised when the pipeline cannot complete successfully."""


def run_pipeline(
    pipeline_config: PipelineConfig | None = None,
    generator_config: GeneratorConfig | None = None,
) -> PipelineResult:
    """Run generation, validation, deduplication, split, and reporting."""

    cfg = pipeline_config or PipelineConfig()
    _validate_pipeline_config(cfg)
    component_config = generator_config or load_configs(cfg.config_dir)
    assert_valid_config(component_config)

    raw_samples = generate_samples(
        cfg.sample_count,
        seed=cfg.seed,
        config=component_config,
    )
    save_raw_outputs(raw_samples, cfg.raw_dir)

    validation_result = validate_samples(raw_samples, component_config)
    save_validation_outputs(
        validation_result,
        output_dir=cfg.processed_dir,
        report_path=cfg.stats_dir / "validation_report.json",
    )

    if validation_result.invalid_samples and cfg.fail_on_invalid:
        raise PipelineError(
            f"Validation rejected {len(validation_result.invalid_samples)} samples."
        )

    deduplicated_samples, duplicate_records = deduplicate_samples(
        validation_result.valid_samples
    )
    train_samples, val_samples = split_samples(
        deduplicated_samples,
        val_ratio=cfg.val_ratio,
        seed=cfg.seed,
    )
    save_split_outputs(train_samples, val_samples, cfg.processed_dir)

    distribution_report = build_distribution_report(
        deduplicated_samples,
        component_config,
        validation_result,
        duplicate_records,
        cfg,
    )
    pipeline_report = build_pipeline_report(
        raw_samples=raw_samples,
        validation_result=validation_result,
        deduplicated_samples=deduplicated_samples,
        duplicate_records=duplicate_records,
        train_samples=train_samples,
        val_samples=val_samples,
        config=component_config,
        pipeline_config=cfg,
    )
    save_reports(distribution_report, pipeline_report, cfg.stats_dir)

    return PipelineResult(
        generated_count=len(raw_samples),
        valid_count=len(validation_result.valid_samples),
        invalid_count=len(validation_result.invalid_samples),
        deduplicated_count=len(deduplicated_samples),
        duplicate_count=len(duplicate_records),
        train_count=len(train_samples),
        val_count=len(val_samples),
        distribution_report=distribution_report,
        validation_report=validation_result.report,
        pipeline_report=pipeline_report,
    )


def save_raw_outputs(samples: list[dict[str, Any]], raw_dir: Path | str) -> None:
    """Save semantic seed inputs and raw generated samples."""

    raw_path = Path(raw_dir)
    raw_path.mkdir(parents=True, exist_ok=True)
    seed_data = [sample["semantic_input"] for sample in samples]
    _write_json(raw_path / "seed_data.json", seed_data)
    _write_json(raw_path / "template_generated.json", samples)


def deduplicate_samples(
    samples: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deduplicate samples by sample_id or normalized content hash."""

    deduplicated: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    seen_keys: dict[str, str | None] = {}

    for sample in samples:
        key = _dedupe_key(sample)
        sample_id = sample.get("sample_id")
        if key in seen_keys:
            duplicates.append(
                {
                    "sample_id": sample_id,
                    "duplicate_of": seen_keys[key],
                    "dedupe_key": key,
                }
            )
            continue
        seen_keys[key] = sample_id
        deduplicated.append(sample)

    return deduplicated, duplicates


def split_samples(
    samples: list[dict[str, Any]],
    val_ratio: float = 0.2,
    seed: int = 42,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deterministically split samples into train and validation sets."""

    if not 0 <= val_ratio < 1:
        raise PipelineError("val_ratio must be in [0, 1).")
    shuffled = list(samples)
    random.Random(seed).shuffle(shuffled)

    if not shuffled or val_ratio == 0:
        return shuffled, []

    val_count = int(len(shuffled) * val_ratio)
    if val_count == 0 and len(shuffled) > 1:
        val_count = 1
    if val_count >= len(shuffled):
        val_count = len(shuffled) - 1

    val_samples = shuffled[:val_count]
    train_samples = shuffled[val_count:]
    return train_samples, val_samples


def save_split_outputs(
    train_samples: list[dict[str, Any]],
    val_samples: list[dict[str, Any]],
    processed_dir: Path | str,
) -> None:
    """Save train and validation splits."""

    processed_path = Path(processed_dir)
    processed_path.mkdir(parents=True, exist_ok=True)
    _write_json(processed_path / "train.json", train_samples)
    _write_json(processed_path / "val.json", val_samples)


def build_distribution_report(
    samples: list[dict[str, Any]],
    config: GeneratorConfig,
    validation_result: ValidationResult,
    duplicate_records: list[dict[str, Any]],
    pipeline_config: PipelineConfig,
) -> dict[str, Any]:
    """Build a data distribution report for deduplicated valid samples."""

    component_types = {
        component["id"]: component["type"]
        for component in config.component_library["components"]
    }
    by_task_type: Counter[str] = Counter()
    by_payload: Counter[str] = Counter()
    by_route_mode: Counter[str] = Counter()
    by_stage_count: Counter[str] = Counter()
    by_action_count: Counter[str] = Counter()
    by_component: Counter[str] = Counter()
    by_robot_ctrl: Counter[str] = Counter()
    by_svr: Counter[str] = Counter()
    failure_metrics = _failure_metrics(samples, config)

    for sample in samples:
        semantic_input = sample.get("semantic_input", {})
        by_task_type[semantic_input.get("task_type", "unknown")] += 1
        by_payload[semantic_input.get("payload", "unknown")] += 1
        by_route_mode[semantic_input.get("route_mode", "unknown")] += 1

        stages = sample.get("target_topology", {}).get("stages", [])
        by_stage_count[str(len(stages))] += 1
        action_total = 0
        for stage in stages:
            actions = stage.get("component", [])
            action_total += len(actions)
            for action in actions:
                name = action.get("name", "unknown")
                by_component[name] += 1
                if component_types.get(name) == "ROBOT_CTRL":
                    by_robot_ctrl[name] += 1
                elif component_types.get(name) == "SVR":
                    by_svr[name] += 1
        by_action_count[str(action_total)] += 1

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "pipeline_version": PIPELINE_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seed": pipeline_config.seed,
        "requested_total": pipeline_config.sample_count,
        "generated_total": validation_result.report["total"],
        "valid_before_dedup": validation_result.report["valid"],
        "invalid": validation_result.report["invalid"],
        "duplicate_count": len(duplicate_records),
        "total": len(samples),
        "by_task_type": dict(sorted(by_task_type.items())),
        "by_payload": dict(sorted(by_payload.items())),
        "by_route_mode": dict(sorted(by_route_mode.items())),
        "by_stage_count": _sort_numeric_counter(by_stage_count),
        "by_action_count": _sort_numeric_counter(by_action_count),
        "by_component": dict(sorted(by_component.items())),
        "by_robot_ctrl": dict(sorted(by_robot_ctrl.items())),
        "by_svr": dict(sorted(by_svr.items())),
        **failure_metrics,
    }


def build_pipeline_report(
    raw_samples: list[dict[str, Any]],
    validation_result: ValidationResult,
    deduplicated_samples: list[dict[str, Any]],
    duplicate_records: list[dict[str, Any]],
    train_samples: list[dict[str, Any]],
    val_samples: list[dict[str, Any]],
    config: GeneratorConfig,
    pipeline_config: PipelineConfig,
) -> dict[str, Any]:
    """Build a compact execution report for the pipeline run."""

    failure_metrics = _failure_metrics(deduplicated_samples, config)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "pipeline_version": PIPELINE_VERSION,
        "generator_version": GENERATOR_VERSION,
        "sample_count_requested": pipeline_config.sample_count,
        "seed": pipeline_config.seed,
        "val_ratio": pipeline_config.val_ratio,
        "fail_on_invalid": pipeline_config.fail_on_invalid,
        "generated_count": len(raw_samples),
        "valid_count": len(validation_result.valid_samples),
        "invalid_count": len(validation_result.invalid_samples),
        "deduplicated_count": len(deduplicated_samples),
        "duplicate_count": len(duplicate_records),
        "train_count": len(train_samples),
        "val_count": len(val_samples),
        "validation_issue_count": validation_result.report["issue_count"],
        "validation_issue_counts": validation_result.report["issue_counts"],
        "duplicate_records": duplicate_records,
        **failure_metrics,
        "output_files": _output_files(pipeline_config),
    }


def save_reports(
    distribution_report: dict[str, Any],
    pipeline_report: dict[str, Any],
    stats_dir: Path | str,
) -> None:
    """Save distribution and pipeline reports."""

    stats_path = Path(stats_dir)
    stats_path.mkdir(parents=True, exist_ok=True)
    _write_json(stats_path / "distribution_report.json", distribution_report)
    _write_json(stats_path / "pipeline_report.json", pipeline_report)


def _validate_pipeline_config(config: PipelineConfig) -> None:
    if config.sample_count < 0:
        raise PipelineError("sample_count must be non-negative.")
    if not 0 <= config.val_ratio < 1:
        raise PipelineError("val_ratio must be in [0, 1).")


def _dedupe_key(sample: dict[str, Any]) -> str:
    sample_id = sample.get("sample_id")
    if isinstance(sample_id, str) and sample_id:
        return f"id:{sample_id}"
    payload = json.dumps(
        {
            "semantic_input": sample.get("semantic_input"),
            "target_topology": sample.get("target_topology"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return f"content:{digest}"


def _sort_numeric_counter(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: int(item[0])))


def _failure_metrics(
    samples: list[dict[str, Any]],
    config: GeneratorConfig,
) -> dict[str, Any]:
    component_types = {
        component["id"]: component["type"]
        for component in config.component_library["components"]
    }
    by_failure_policy: Counter[str] = Counter()
    failure_branch_count = 0
    failure_enabled_count = 0
    guarded_robot_ctrl_stage_count = 0

    for sample in samples:
        metadata = sample.get("metadata", {}).get("failure_strategy", {})
        if isinstance(metadata, dict):
            branch_count = metadata.get("branch_count", 0)
            if isinstance(branch_count, int):
                failure_branch_count += branch_count
            if metadata.get("enabled") is True:
                failure_enabled_count += 1
            policies = metadata.get("policies", [])
            if isinstance(policies, list):
                for policy in policies:
                    if isinstance(policy, str):
                        by_failure_policy[policy] += 1

        for stage in sample.get("target_topology", {}).get("stages", []):
            if not isinstance(stage, dict) or not isinstance(stage.get("component"), list):
                continue
            robot_count = sum(
                1
                for action in stage["component"]
                if component_types.get(action.get("name")) == "ROBOT_CTRL"
            )
            if robot_count > 1:
                guarded_robot_ctrl_stage_count += 1

    return {
        "failure_enabled_count": failure_enabled_count,
        "failure_branch_count": failure_branch_count,
        "guarded_robot_ctrl_stage_count": guarded_robot_ctrl_stage_count,
        "by_failure_policy": dict(sorted(by_failure_policy.items())),
    }


def _output_files(config: PipelineConfig) -> dict[str, str]:
    return {
        "seed_data": str(config.raw_dir / "seed_data.json"),
        "raw_samples": str(config.raw_dir / "template_generated.json"),
        "validated_samples": str(config.processed_dir / "validated_samples.json"),
        "invalid_samples": str(config.processed_dir / "invalid_samples.json"),
        "train": str(config.processed_dir / "train.json"),
        "val": str(config.processed_dir / "val.json"),
        "distribution_report": str(config.stats_dir / "distribution_report.json"),
        "validation_report": str(config.stats_dir / "validation_report.json"),
        "pipeline_report": str(config.stats_dir / "pipeline_report.json"),
    }


def _write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the UAV dataset generation pipeline.")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--config-dir", type=Path, default=Path("config"))
    parser.add_argument("--raw-dir", type=Path, default=Path("raw"))
    parser.add_argument("--processed-dir", type=Path, default=Path("processed"))
    parser.add_argument("--stats-dir", type=Path, default=Path("stats"))
    parser.add_argument("--fail-on-invalid", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config = PipelineConfig(
        sample_count=args.count,
        seed=args.seed,
        val_ratio=args.val_ratio,
        config_dir=args.config_dir,
        raw_dir=args.raw_dir,
        processed_dir=args.processed_dir,
        stats_dir=args.stats_dir,
        fail_on_invalid=args.fail_on_invalid,
    )
    result = run_pipeline(config)
    print(
        json.dumps(
            {
                "generated_count": result.generated_count,
                "valid_count": result.valid_count,
                "invalid_count": result.invalid_count,
                "deduplicated_count": result.deduplicated_count,
                "duplicate_count": result.duplicate_count,
                "train_count": result.train_count,
                "val_count": result.val_count,
                "pipeline_report": str(config.stats_dir / "pipeline_report.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
