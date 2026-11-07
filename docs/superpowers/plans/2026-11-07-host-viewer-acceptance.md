# B9 host viewer acceptance evidence

Date: 2026-11-07. **Offline integration and a 35-second physical viewer run are complete.** Current DATA transport still has sequence gaps; lossless A4 and a sampling ceiling are not certified. Firmware output is not an independent sensor calibration. The main agent completed hardware runs after concentrated independent review.

## Executed offline commands

From the repository root, using the existing Python 3.9 environment:

```powershell
python tools/hosttest/host_acceptance.py --synthetic --out-dir build/host-acceptance/b9-synthetic-final
python tools/hosttest/host_acceptance.py --replay build/hardware/t7-int-recovery.json --out-dir build/host-acceptance/b9-fault-final
python -m pytest tools/hosttest/test_host_acceptance.py -q
```

Both acceptance commands exited 0 and their `report.json` files contain `passed: true`; the tests returned **9 passed in 5.95 s**, exit 0. The local Python environment additionally printed a pyreadline3 destructor warning after pytest completed; it was not a Qt callback failure. Neither acceptance run opened a physical port, flashed firmware, displayed a native window/dialog, or touched user preferences.

## Cross-module evidence

The runner assembles the production `MainWindow`, production `SerialSource` and reader QThread, production incremental codec, production `CsvWriter`, logging setup, and settings manager. Offline transport supplies fragmented wire bytes via an injected `FakeSerial` factory; it does not replace the source with a signal-only fake. Qt uses its process-local offscreen platform, Fusion style, global production stylesheet, and existing Windows fonts loaded only into the process. Screenshots were inspected: Chinese labels and the four synthetic curves are readable.

| Criterion | Offline result | Physical acceptance |
|---|---|---|
| A4 DATA and global sequence | Synthetic: 100 DATA + one status + ERR_NONE; zero sequence gaps, parser skips, duplicates, queue drops | Pending live evidence review |
| A5 live curves | Synthetic: 100 samples rendered in each of four curves; Kalman changes magnetic display only | Pending live run |
| A6 logs and resources | Actual HEALTH implementation records process CPU/RSS/thread count and serial queue/rate/frame/byte counters; START/STOP and file events present | Natural 30-second timer still pending live run |
| A7 fault behavior | Full historical fault replay: no plot data, no numeric CSV, explicit SENSOR_DIAG, bounded warnings; synthetic nominal 100 Hz diagnostics also remain gated | Historical capture is fault evidence, not current hardware state |
| A8 CSV | All 100 synthetic rows match independent raw/885 and temperature arithmetic to four decimals; target hidden while open, published after stop, no temporary residue | Pending healthy live CSV/raw comparison |

Synthetic first raw sample is `(885, -1770, 442, 17570)`. Its CSV row is `1.0000,-2.0000,0.4994,25.9966`. Synthetic status uses sensitivity 885, READY/CFG/HSE flags, `Conv=0x01`, `Device=0x10`, and `INT_OK=0`, exercising the polling-compatible path without treating the INT warning as a sensor fault. Initial unknown metadata and ERR_NONE stay neutral. Source metadata invalidation then blocks further plotted data and CSV start. Disconnect/close stops the source worker, source/UI timers and UI logging handler, while settings save only beneath the artifact directory.

The full fault replay has **1,003 historical records but 1,002 frames accepted by the current parser**: 991 diagnostics, 11 statuses, zero DATA. Historical seq 107 raw bytes `aaee6b07341c00000000aaee` contain nonzero reserved ERROR bytes; the hardened codec rejects this record unchanged. Result: 12 skipped parser bytes and 124 missing global sequence frames, with zero queue loss. The historical capture itself reported 159 discarded bytes and 123 lost frames. Those original discarded bytes were not saved in `records[].raw_hex` and cannot be reconstructed by replay; its original timing is also not reproduced. The runner reports this distinction explicitly. Last replay status is `Device=0x14`, `Conv=0x73`; this is historical fault evidence.

Final artifacts (all ignored build outputs):

- `build/host-acceptance/b9-synthetic-final/report.json`, `window.png`, `samples.csv`, `ui-log.txt`, `settings.json`, and `logs/host_acceptance_20261107_135107.log`.
- `build/host-acceptance/b9-fault-final/report.json`, `window.png`, `ui-log.txt`, `settings.json`, and `logs/host_acceptance_20261107_135111.log` (no numeric CSV).
- Each pytest subprocess also writes its own unique `build/host-acceptance/pytest-<uuid>/` report and artifacts.

Earlier exploratory `b9-*-01/02` outputs are not final evidence. In particular, the first fault attempt timed out with an excessively fine replay sleep; final replay is accelerated and reports its timing limitation.

## Main-agent handoff: optional physical run

Do not run this concurrently with another serial capture. The main agent reported a later polling capture (`polling100-fresh1.json`: 989 DATA, 98.447 Hz over 10.046 s, zero errors, 11 gaps, 63 skipped bytes) after the offline work began. That separate observation does not substitute for the live viewer acceptance below. Its provenance and physical conclusions remain with the main agent.

After independent review, the main agent may explicitly open COM9 using a **new** output directory:

```powershell
python tools/hosttest/host_acceptance.py --port COM9 --baud 115200 --seconds 35 --out-dir build/host-acceptance/b9-live-poll100-01
```

There is no default port, no automatic serial enumeration/open, and modes are mutually exclusive. `--help` exits before Qt imports. `--seconds` is finite and bounded to 2–120 seconds; default is 4 offline and 35 live. A 35-second live run allows the production 30-second HEALTH timer to fire naturally. The runner never edits firmware or port configuration. Existing output directories and paths outside checkout `build/host-acceptance` are rejected, including resolved paths redirected outside the checkout.

The patched save picker supplies only `<out-dir>/samples.csv`; no picker is displayed. CSV begins on the first usable status and closes atomically. Per-sample expectations follow received raw values and current valid status sensitivity. After review, `--port` explicitly requires current healthy metadata, DATA, numeric CSV rows, and four nonempty curves. A fault-only live run therefore exits nonzero; offline fault replay remains a valid passing fault-path test. A data-bearing report retains `physical_acceptance: false` and `healthy_hardware_A4_A5: REVIEW_LIVE_EVIDENCE` for separate physical evidence review, including the zero-gap A4 criterion.

Review `report.json`, `window.png`, CSV, and the complete log together. Compare frame/sample counts, all four curve lengths, CSV values, skipped **bytes**, missing wire **frames**, delivery queue **frames**, actual resource metrics and the natural HEALTH event. The displayed SEQ/rate updates on the production 200 ms stats cadence and can lag the final transport snapshot. Raw sensor values are evidence of firmware output, not an independent sensor calibration. Cleanup executes in `finally`; source workers and owned handlers are closed and temporary settings/dialog patches are restored.

## Executed physical runs and final checks

Commit `7a0367e` contains the reviewed runner and explicit live health gates. Final host/capture/acceptance regression: **319 passed in 13.45 seconds**. The separate bus recovery checks returned636/636, polling679/679 and IRQ2253/2253, including the rate/mode compile matrix.

`b9-live-poll100-01`: after the sweep and firmware restoration, the sensor bus remained stuck. The 35-second viewer run correctly returned `passed: false` / exit1; no healthy data was certified. Read-only SWD showed PB7 SDA low and I2C BUSY. Firmware `682e67e` added bounded foreground bus recovery, was reviewed, built without warnings, flashed with verification, and reset.

```powershell
python tools/hosttest/host_acceptance.py --port COM9 --baud 115200 --seconds 35 --out-dir build/host-acceptance/b9-live-poll100-recovery-02
```

This actual physical run exited0 with `passed: true`. The main agent inspected `window.png`: XYZ and temperature curves and Chinese labels are readable.

| Evidence | Physical result |
|---|---|
| Delivered at snapshot | 3491 DATA,40 status,6 ERROR |
| Current metadata | version0x12,flags0x4C,885 LSB/mT,100 Hz,DeviceStatus0x10,current diagnostic bits clear |
| Curves | Four curves,2000 retained points each |
| CSV | 3469 numeric rows; every row matches received raw XYZ divided by received sensitivity and raw temperature conversion |
| Rate | Snapshot99.700 Hz; natural30-second HEALTH99.850 Hz |
| Loss counters | 112 inferred SEQ gaps,12 skipped bytes,0 delivery queue drops,0 duplicates/out-of-order |
| Natural HEALTH | CPU26.7%,RSS93.4 MiB,delta+24.4 MiB,27 threads,uptime30 seconds |
| Cleanup | CSV published,worker/timers stopped,UI log handler removed,isolated settings saved,no temporary residue or callback exceptions |

Six I2C_NACK frames arrived at the beginning before healthy metadata; the port was not flushed. Old buffered frames remain a possible explanation, not a proven cause. Report `source_stats` is the screenshot/CSV snapshot; STOP logs later show3512 DATA because acquisition continues during artifact saving. These distinct snapshots must not be combined into one rate or row count. CSV begins after usable status, so it deliberately has fewer rows than all delivered DATA.

This certifies the physical A5 curves, A6 logging and raw-to-CSV conversion/normal close portion of A8. A4 zero-loss remains unpassed. Actual cable-unplug CSV interruption is not certified.

After the user physically power-cycled the board and sensor, `build/hardware/polling100-coldboot-01.json` plus complete `.bin` captured979 DATA over10.047 seconds,97.442 Hz,10 statuses,0 ERROR,current and cumulative sensor errors0. Twenty inferred SEQ gaps and141 skipped bytes remained. Cold startup works; cycling power did not eliminate the transport issue. All generated artifacts remain local and ignored.
