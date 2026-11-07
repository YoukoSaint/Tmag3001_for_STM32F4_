"""CLI boundaries plus subprocess integration across real Qt/source/parser/CSV."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

RUNNER = Path(__file__).with_name("host_acceptance.py")
SPEC = importlib.util.spec_from_file_location("host_acceptance", RUNNER)
acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)


@pytest.mark.parametrize("args", [[], ["--synthetic", "--port", "COM9"],
    ["--synthetic", "--seconds", "nan"], ["--synthetic", "--seconds", "121"],
    ["--port", " "]])
def test_cli_rejects_ambiguous_or_unbounded_modes(args):
    with pytest.raises(SystemExit):
        acceptance.parse_args(args)


def test_defaults_never_imply_a_physical_port():
    assert acceptance.parse_args(["--synthetic"]).port is None
    assert acceptance.parse_args(["--synthetic"]).seconds == 4
    assert acceptance.parse_args(["--port", "COM9"]).seconds == 35


def test_live_fault_or_gated_data_cannot_pass_healthy_acceptance():
    report = {"checks": {}, "delivered": {"data": 0}, "csv_numeric_rows": 0,
              "curve_points": [0] * 4}
    acceptance.require_live_data(report, False)
    assert not any(report["checks"].values())
    report.update(delivered={"data": 20}, csv_numeric_rows=20, curve_points=[20] * 4)
    acceptance.require_live_data(report, True)
    assert all(report["checks"].values())
    # Receiving DATA alone cannot hide a later invalidated status or empty curve.
    acceptance.require_live_data(report, False)
    assert not all(report["checks"].values())
    report["curve_points"][-1] = 0
    acceptance.require_live_data(report, True)
    assert not all(report["checks"].values())


def test_output_containment_and_no_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr(acceptance, "ROOT", tmp_path)
    base = tmp_path / "build" / "host-acceptance"
    monkeypatch.setattr(acceptance, "ARTIFACT_ROOT", base)
    output = acceptance.reserve_output(base / "run")
    assert output.is_dir()
    with pytest.raises(FileExistsError):
        acceptance.reserve_output(output)
    for path in (base, tmp_path / "elsewhere", base / ".." / "escape"):
        with pytest.raises(ValueError):
            acceptance.reserve_output(path)


def execute(mode_args):
    output = acceptance.ARTIFACT_ROOT / ("pytest-" + uuid.uuid4().hex)
    result = subprocess.run([sys.executable, str(RUNNER), *mode_args, "--out-dir", str(output)],
                            cwd=acceptance.ROOT, capture_output=True, timeout=20)
    assert result.returncode == 0, (result.stdout, result.stderr)
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["passed"] and all(report["checks"].values())
    assert not report["physical_acceptance"]
    assert report["healthy_hardware_A4_A5"] == "PENDING"
    return report, output


def test_synthetic_actual_qthread_ui_csv_lifecycle():
    report, output = execute(["--synthetic"])
    assert report["csv_numeric_rows"] == 100
    assert report["actual_first_csv"] == ["1.0000", "-2.0000", "0.4994", "25.9966"]
    assert report["curve_points"] == [100] * 4
    assert report["source_stats"]["samples"] == 100
    assert report["diagnostic_phase"]["source_stats"]["errors"] == 100
    assert (output / "window.png").stat().st_size > 10000


def test_historical_fault_raw_replay_is_reparsed_without_reencoding():
    # Fixture deliberately contains an old-parser-accepted malformed ERROR.
    # The current codec must reject its reserved bytes, retaining the other frames.
    sys.path.insert(0, str(acceptance.ROOT / "host"))
    from tmag_viewer import protocol as p
    folder = acceptance.reserve_output()
    frames = [p.encode_status(105, 0x4C, 0, 885, 100, 1, 0x73, 0x14),
              p.encode_error(106, 7, 0x34, 0x1C), bytes.fromhex("aaee6b07341c00000000aaee"),
              p.encode_error(108, 7, 0x34, 0x1C)]
    fixture = folder / "fixture.json"
    fixture.write_text(json.dumps({"records": [{"raw_hex": f.hex()} for f in frames]}), encoding="utf-8")
    report, _ = execute(["--replay", str(fixture)])
    assert report["historical_records"] == 4
    assert report["records_rejected_by_current_codec"] == 1
    assert report["source_stats"]["frames"] == 3
    assert report["source_stats"]["skipped_bytes"] == 12
    assert report["source_stats"]["dropped_frames"] == 1
    assert report["csv_numeric_rows"] == report["plotted_samples"] == 0
