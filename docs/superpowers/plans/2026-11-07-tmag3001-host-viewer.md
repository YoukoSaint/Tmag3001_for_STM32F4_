# TMAG3001 PC 端可视化应用 Implementation Plan

> **2026-11-07 执行前更正**：v1.2（0x12）仍为待实现草案。线协议唯一契约是 `docs/protocol/TMAG3001_Protocol.md`，进度见 `docs/superpowers/plans/2026-11-07-execution-status.md`。CRC8/crc8/tmag_crc8 是遗留命名，算法仅为字节 XOR。


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 PyQt5 做一个实时磁力计可视化桌面应用，按 `UI_palette` 的架构思想（颜色角色单一真相源 + 主题面板 + 设置持久化）重构，按 `Logging_Standard_for_Agent` 的规范实现全部日志，并正确消费固件 v1.2 的 12 字节二进制协议。

**Architecture:** `host/tmag_viewer/` 是包，`protocol.py`（协议，与固件一一对应）、`log_setup.py`（日志）、`color_scheme.py`（配色）、`settings_manager.py`（持久化）四个模块**不依赖 Qt**，可纯 pytest 测试；`serial_source.py` 用 QThread 读串口并通过 Qt 信号送数据；`plot_widgets.py` / `color_panel.py` / `main_window.py` 负责呈现。协议层用**跨语言 golden vector**（同一组硬编码字节）与固件 C 实现对齐。

**Tech Stack:** Python 3.9.12（Anaconda）· PyQt5 5.15.11 · pyqtgraph 0.13.7 · pyserial 3.5 · numpy 2.0.2 · psutil 5.8.0 · pytest 8.4.2

**Design Spec:** `docs/superpowers/specs/2026-11-07-tmag3001-f411-pipeline-design.md` §7
**Firmware Plan:** `docs/superpowers/plans/2026-11-07-tmag3001-f411-firmware-pipeline.md`（协议契约的**唯一权威**）

---

## Global Constraints

- **协议**：以 `docs/protocol/TMAG3001_Protocol.md` 为唯一线协议权威，固件头文件须与其一致。三类帧统一 **12 字节**；`[0]=0xAA`；`[1]` 为 TYPE（`0x55` 数据 / `0x56` 状态 / `0xEE` 错误）；`[2]` 为 SEQ（0x00–0xFF 循环）；`[11]` 为 CRC-8（**初值 0x00、逐字节 XOR、无反射，覆盖字节 `[2..10]`**）。
- **量程与灵敏度**：PC 端**禁止硬编码** 446 或 885。灵敏度必须从状态帧的 `SENS` 字段读取；未收到状态帧前不显示数值曲线，只显示"等待状态帧"。
- **时钟源可见性**：状态帧 `FLAGS` bit6 `CLK_SRC_HSE` 指示固件是否跑在 25 MHz 晶振上；为 0 时（已回退内部 RC）PC 端须在日志面板提示一次"时钟精度受限"。
- **日志**：全部在 PC 端。严格遵循 `Logging_Standard_for_Agent`——模块级 `logging.getLogger(__name__)`、入口调用 `setup_logging()`、串口相关行带 `[transport=serial][addr=COM9@115200]`、每 30–60 s 一行 `HEALTH`、日志调用禁用 f-string、CSV 用 `tmp + os.replace` 原子写。
- **UI 架构**：严格遵循 `UI_palette`——`ColorScheme` 用**类属性**（不是字典）作唯一真相源、`get_stylesheet()` 是**函数**（每次重读属性）、QSS 应用于 `QApplication.instance()` 而非 `QMainWindow`、pyqtgraph 画笔用 `hex_to_rgba()` 生成。
- **黄金向量**：固件与 PC 端必须对同一组硬编码字节给出相同结果（见 Task B2 的五组 golden vector）。
- **运行环境**：Python 脚本**必须从仓库目录运行**，**禁止**在 `%TEMP%` 下运行脚本（该目录存在残留 `inspect.py` 等模块，会污染 stdlib 导入并触发 `ImportError: cannot import name 'currentframe'`）。
- **不新增依赖**：只用已装的 PyQt5 / pyqtgraph / pyserial / numpy / psutil / pytest，**不得** `pip install` 新包。
- **文件落位**：所有新文件位于 `F:\youko_repo\Tmag3001_for_STM32F4_\host\` 之内。
- **板载 UI**：不做。PC 端是唯一的可视化载体。

---

## File Structure

### 新建

| 路径 | 职责 |
|---|---|
| `host/requirements.txt` | 依赖清单与版本下限 |
| `host/pytest.ini` | pytest 配置（`testpaths`、`pythonpath`） |
| `host/run.py` | 应用入口：配置日志 → 建 QApplication → 应用 QSS → 显示主窗口 |
| `host/tmag_viewer/__init__.py` | 包标记，暴露 `__version__` |
| `host/tmag_viewer/protocol.py` | 帧编解码 + CRC-8 + 错误码表 + 数据类（**无 Qt 依赖**） |
| `host/tmag_viewer/log_setup.py` | `setup_logging()`（**无 Qt 依赖**） |
| `host/tmag_viewer/color_scheme.py` | `ColorScheme` 颜色角色 + `get_stylesheet()` + `hex_to_rgba()`（**无 Qt 依赖**） |
| `host/tmag_viewer/settings_manager.py` | JSON 持久化：深度合并 + 原子写（**无 Qt 依赖**） |
| `host/tmag_viewer/serial_source.py` | 串口读取线程 + 帧分发 + 丢帧/速率统计 |
| `host/tmag_viewer/csv_writer.py` | CSV 原子写（**无 Qt 依赖**） |
| `host/tmag_viewer/plot_widgets.py` | pyqtgraph 图表（XYZ 叠加主图 + 温度副图） |
| `host/tmag_viewer/color_panel.py` | 颜色角色编辑面板 |
| `host/tmag_viewer/main_window.py` | 布局编排 + 状态栏 + 日志面板 + 健康监控 |
| `host/tests/test_protocol.py` | 协议单元测试 + **跨语言 golden vector** |
| `host/tests/test_log_setup.py` | 日志规范测试 |
| `host/tests/test_color_scheme.py` | 配色模块测试 |
| `host/tests/test_settings_manager.py` | 持久化测试 |
| `host/tests/test_csv_writer.py` | CSV 原子写测试 |

---

### Task B1: host 骨架与测试基建

**Files:**
- Create: `host/requirements.txt`, `host/pytest.ini`, `host/tmag_viewer/__init__.py`, `host/tests/__init__.py`, `host/run.py`

**Interfaces:**
- Consumes: 无
- Produces: `host` 包可导入；`pytest` 可在 `host/` 下运行；后续任务都在此骨架上加模块。

- [ ] **Step 1: 写 `host/requirements.txt`**

```
# 版本下限按本机实测环境填写
PyQt5>=5.15,<6
pyqtgraph>=0.13
pyserial>=3.5
numpy>=1.24
psutil>=5.8
pytest>=8.0
```

- [ ] **Step 2: 写 `host/pytest.ini`**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
addopts = -q
filterwarnings =
    ignore::DeprecationWarning
```

- [ ] **Step 3: 写包标记**

`host/tmag_viewer/__init__.py`：
```python
"""TMAG3001 磁场实时可视化应用。"""

__version__ = "1.2.0"
```

`host/tests/__init__.py`：空文件。

- [ ] **Step 4: 写 `host/run.py`（先只放最小可运行外壳，后续任务替换）**

```python
"""TMAG3001 可视化应用入口。

用法:
    python host/run.py
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# 允许以 `python host/run.py` 直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    from tmag_viewer.log_setup import setup_logging

    log_path = setup_logging("tmag_viewer", str(Path(__file__).resolve().parent / "logs"))
    logging.getLogger(__name__).info("Logging initialized: %s", log_path)

    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from tmag_viewer.main_window import MainWindow

    win = MainWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
```

> `main_window.py` 在 Task B8 才创建；在 B1 阶段 `run.py` 暂时无法完整运行，这是预期的——B1 的验收是 pytest 能跑。

- [ ] **Step 5: 验证 pytest 基建**

Run: `cd F:\youko_repo\Tmag3001_for_STM32F4_\host; C:\ProgramData\Anaconda3\python.exe -m pytest`
Expected: `no tests ran`（退出码 5，这是 pytest 的正常"无测试"返回码）。

- [ ] **Step 6: 提交**

```
chore(host): 建立 PC 端工程骨架与 pytest 基建

host/ 包结构、requirements、pytest.ini、入口 run.py。
Python 脚本一律在仓库目录内运行（%TEMP% 有残留模块会污染 stdlib 导入）。
```

---

### Task B2: 协议层（与固件 golden vector 对齐）

**Files:**
- Create: `host/tmag_viewer/protocol.py`
- Create: `host/tests/test_protocol.py`

**Interfaces:**
- Consumes: Task B1 的骨架；固件计划的 `App/Inc/tmag_proto.h`
- Produces:
  - `crc8(data: bytes) -> int`
  - `encode_data(seq, x_raw, y_raw, z_raw, temp_raw) -> bytes`
  - `encode_status(seq, flags, range_code, sensitivity, sample_rate_hz, err_count, conv_status, device_status) -> bytes`
  - `encode_error(seq, err_code, i2c_addr=0, reg_addr=0) -> bytes`
  - `decode_frame(frame: bytes) -> Frame | None`
  - `Frame` 数据类：`kind`、`seq`，以及按 kind 不同的字段
  - 常量 `FRAME_SIZE`、`SYNC`、`TYPE_DATA`、`TYPE_STATUS`、`TYPE_ERROR`、`PROTO_VERSION`
  - `ERR_NAMES: dict[int, str]`
  - `FLAG_*` 常量

- [ ] **Step 1: 先写失败的测试 `host/tests/test_protocol.py`**

```python
"""协议层单元测试。

五组 golden vector 与固件 C 实现（App/Src/tmag_proto.c）逐字节一致，
是固件与 PC 端对齐的唯一保证。
"""
from __future__ import annotations

import struct

import pytest

from tmag_viewer import protocol as P


# ── golden vectors（与固件 C 实现同源）──
GOLDEN_DATA = bytes.fromhex("AA550105D8002CFF1E44683D")
GOLDEN_STATUS = bytes.fromhex("AA5642122C0375640001006F")
GOLDEN_ERROR = bytes.fromhex("AAEE0701340E00000000003C")


GOLDEN_STATUS_500 = bytes.fromhex("AA564212AC037532000100B9")
GOLDEN_STATUS_1000 = bytes.fromhex("AA564212AC037564000100EF")

@pytest.mark.parametrize("rate,golden", [(500, GOLDEN_STATUS_500), (1000, GOLDEN_STATUS_1000)])
def test_high_rate_golden(rate, golden):
    out = P.encode_status(0x42, 0x2C, 0, 885, rate, 0, 1, 0)
    assert out == golden
    assert P.decode_frame(out).sample_rate_hz == rate

@pytest.mark.parametrize("rate", [-1, 256, 257, 999, 2551, 1.5, 100.0, True, "100"])
def test_reject_unrepresentable_rate(rate):
    with pytest.raises(ValueError):
        P.encode_status(0x42, 0x2C, 0, 885, rate, 0, 1, 0)

@pytest.mark.parametrize("rate", [0, 1, 255, 260, 2550])
def test_rate_boundaries(rate):
    out = P.encode_status(0x42, 0xEC, 0, 885, rate, 0, 1, 0)
    assert P.decode_frame(out).sample_rate_hz == rate
    assert bool(out[4] & P.FLAG_RATE_X10) == (rate > 255)
    assert out[4] & P.FLAG_CLK_SRC_HSE
    assert out[11] == P.crc8(out[2:11])

def test_unknown_status_version():
    out = bytearray(GOLDEN_STATUS)
    out[3] = 0x13
    out[11] = P.crc8(out[2:11])
    assert P.decode_frame(bytes(out)) is None

def test_crc8_golden():
    assert P.crc8(bytes.fromhex("0105D8002CFF1E")) == 0x11
    assert P.crc8(b"") == 0x00
    assert P.crc8(b"A") == 0x41


def test_encode_data_matches_golden():
    out = P.encode_data(0x01, 1496, 44, -226, 17512)
    assert out == GOLDEN_DATA
    assert len(out) == P.FRAME_SIZE


def test_encode_status_matches_golden():
    out = P.encode_status(
        seq=0x42,
        flags=P.FLAG_SENSOR_READY | P.FLAG_CFG_OK | P.FLAG_INT_PATH_OK,
        range_code=0,
        sensitivity=885,
        sample_rate_hz=100,
        err_count=0,
        conv_status=0x01,
        device_status=0x00,
    )
    assert out == GOLDEN_STATUS


def test_encode_error_matches_golden():
    out = P.encode_error(0x07, P.ERR_I2C_NACK, 0x34, 0x0E)
    assert out == GOLDEN_ERROR


def test_decode_data_frame():
    f = P.decode_frame(GOLDEN_DATA)
    assert f is not None
    assert f.kind == "data"
    assert f.seq == 0x01
    assert (f.x_raw, f.y_raw, f.z_raw, f.temp_raw) == (1496, 44, -226, 17512)


def test_decode_status_frame():
    f = P.decode_frame(GOLDEN_STATUS)
    assert f is not None
    assert f.kind == "status"
    assert f.seq == 0x42
    assert f.version == 0x12
    assert f.range_code == 0
    assert f.sensitivity == 885
    assert f.sample_rate_hz == 100
    assert f.err_count == 0
    assert f.conv_status == 0x01
    assert f.device_status == 0x00
    assert f.sensor_ready is True
    assert f.cfg_ok is True
    assert f.int_path_ok is True


def test_decode_error_frame():
    f = P.decode_frame(GOLDEN_ERROR)
    assert f is not None
    assert f.kind == "error"
    assert f.seq == 0x07
    assert f.err_code == 0x01
    assert f.err_name == "I2C_NACK"


def test_decode_rejects_bad_crc():
    bad = bytearray(GOLDEN_DATA)
    bad[11] ^= 0xFF
    assert P.decode_frame(bytes(bad)) is None


def test_decode_rejects_wrong_sync():
    bad = bytearray(GOLDEN_DATA)
    bad[0] = 0xAB
    assert P.decode_frame(bytes(bad)) is None


def test_decode_rejects_short_frame():
    assert P.decode_frame(GOLDEN_DATA[:11]) is None


def test_sensitivity_lookup_table():
    assert P.SENSITIVITY_TABLE[0] == 885
    assert P.SENSITIVITY_TABLE[1] == 446
    assert P.SENSITIVITY_TABLE[2] == 273
    assert P.SENSITIVITY_TABLE[3] == 137


def test_clock_src_hse_flag_roundtrip():
    """状态帧 bit6：1=晶振，0=回退内部 RC。"""
    frame = P.encode_status(
        seq=0x43,
        flags=P.FLAG_SENSOR_READY | P.FLAG_CFG_OK | P.FLAG_CLK_SRC_HSE,
        range_code=0,
        sensitivity=885,
        sample_rate_hz=100,
        err_count=0,
        conv_status=0x01,
        device_status=0x00,
    )
    f = P.decode_frame(frame)
    assert f is not None
    assert f.clock_from_hse is True
    assert frame[4] == 0x0C | 0x40


def test_all_error_codes_have_names():
    assert set(P.ERR_NAMES) == set(range(0, 10))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd F:\youko_repo\Tmag3001_for_STM32F4_\host; C:\ProgramData\Anaconda3\python.exe -m pytest`
Expected: **收集阶段报错** `ModuleNotFoundError: No module named 'tmag_viewer'` 或 `ImportError: cannot import name 'protocol'`。

- [ ] **Step 3: 写 `host/tmag_viewer/protocol.py`**

```python
"""TMAG3001 串口二进制协议 v1.2（PC 端实现）。

与固件 `App/Src/tmag_proto.c` 一一对应。三类帧统一 12 字节：
    [0]=0xAA  [1]=TYPE  [2]=SEQ  [3..10]=PAYLOAD  [11]=CRC8
CRC-8：初值 0x00，逐字节 XOR，无反射无反转，覆盖字节 [2..10]。

本模块**不依赖 Qt**，可单独用 pytest 测试。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

FRAME_SIZE = 12
SYNC = 0xAA
PROTO_VERSION = 0x12

TYPE_DATA = 0x55
TYPE_STATUS = 0x56
TYPE_ERROR = 0xEE

# 状态帧 FLAGS 位
FLAG_RATE_X10 = 1 << 7
FLAG_RANGE_MASK = 0x03
FLAG_SENSOR_READY = 1 << 2
FLAG_CFG_OK = 1 << 3
FLAG_TRIGGER_INT = 1 << 4
FLAG_INT_PATH_OK = 1 << 5
FLAG_CLK_SRC_HSE = 1 << 6   # 1=SYSCLK 来自 25MHz 晶振，0=已回退内部 RC

# 错误码 → 名称（与固件 tmag_err_code_t 一致）
ERR_NAMES = {
    0x00: "SENSOR_READY",
    0x01: "I2C_NACK",
    0x02: "SENSOR_ID_MISMATCH",
    0x03: "CONFIG_FAIL",
    0x04: "I2C_READ_FAIL",
    0x05: "I2C_TIMEOUT",
    0x06: "NO_CONV",
    0x07: "SENSOR_DIAG",
    0x08: "OVERFLOW",
    0x09: "TX_OVERFLOW",
}
ERR_NONE = 0x00
ERR_I2C_NACK = 0x01
ERR_SENSOR_ID = 0x02
ERR_CONFIG_FAIL = 0x03
ERR_I2C_READ = 0x04
ERR_I2C_TIMEOUT = 0x05
ERR_NO_CONV = 0x06
ERR_SENSOR_DIAG = 0x07
ERR_OVERFLOW = 0x08
ERR_TX_OVERFLOW = 0x09

# 量程 → 灵敏度 (LSB/mT)；与固件 tmag_sensitivity_for_range 一致
SENSITIVITY_TABLE = (885, 446, 273, 137)

RANGE_NAMES = ("±40mT", "±80mT", "±120mT", "±240mT")


@dataclass(frozen=True)
class Frame:
    """解码后的帧。字段按 kind 取用。"""

    kind: str          # "data" | "status" | "error"
    seq: int
    # data
    x_raw: int = 0
    y_raw: int = 0
    z_raw: int = 0
    temp_raw: int = 0
    # status
    version: int = 0
    flags: int = 0
    range_code: int = 0
    sensitivity: int = 0
    sample_rate_hz: int = 0
    err_count: int = 0
    conv_status: int = 0
    device_status: int = 0
    # error
    err_code: int = 0
    err_name: str = ""
    i2c_addr: int = 0
    reg_addr: int = 0

    # 状态位的便捷属性
    @property
    def sensor_ready(self) -> bool:
        return bool(self.flags & FLAG_SENSOR_READY)

    @property
    def cfg_ok(self) -> bool:
        return bool(self.flags & FLAG_CFG_OK)

    @property
    def int_path_ok(self) -> bool:
        return bool(self.flags & FLAG_INT_PATH_OK)

    @property
    def clock_from_hse(self) -> bool:
        """True = 固件跑在 25MHz 晶振上；False = 已回退内部 RC（精度差）。"""
        return bool(self.flags & FLAG_CLK_SRC_HSE)

    @property
    def range_name(self) -> str:
        if 0 <= self.range_code < len(RANGE_NAMES):
            return RANGE_NAMES[self.range_code]
        return "未知"

    def to_mt(self, raw: int, sensitivity: int) -> float:
        """原始 LSB → mT。sensitivity 必须来自状态帧，禁止硬编码。"""
        if sensitivity <= 0:
            return 0.0
        return raw / float(sensitivity)


def crc8(data: bytes) -> int:
    """CRC-8：初值 0x00，逐字节 XOR。"""
    crc = 0
    for b in data:
        crc ^= b
    return crc


def _finish(frame: bytearray) -> bytes:
    frame[11] = crc8(bytes(frame[2:11]))
    return bytes(frame)


def encode_data(seq: int, x_raw: int, y_raw: int, z_raw: int, temp_raw: int) -> bytes:
    """编码数据帧。用于单元测试与离线模拟器。"""
    f = bytearray(FRAME_SIZE)
    f[0] = SYNC
    f[1] = TYPE_DATA
    f[2] = seq & 0xFF
    struct.pack_into(">hhhh", f, 3, x_raw, y_raw, z_raw, temp_raw)
    return _finish(f)


def encode_status(
    seq: int,
    flags: int,
    range_code: int,
    sensitivity: int,
    sample_rate_hz: int,
    err_count: int,
    conv_status: int,
    device_status: int,
) -> bytes:
    """编码名义配置 Hz；不可表示时拒绝，不截断。"""
    if type(sample_rate_hz) is not int or not 0 <= sample_rate_hz <= 2550:
        raise ValueError("sample rate must be an integer in 0..2550 Hz")
    rate = sample_rate_hz
    rate_flag = 0
    if rate > 255:
        if rate % 10:
            raise ValueError("rates above 255 Hz must be exact multiples of 10")
        rate //= 10
        rate_flag = FLAG_RATE_X10
    f = bytearray(FRAME_SIZE)
    f[0] = SYNC
    f[1] = TYPE_STATUS
    f[2] = seq & 0xFF
    f[3] = PROTO_VERSION
    f[4] = (flags & ~(FLAG_RANGE_MASK | FLAG_RATE_X10)) | (range_code & FLAG_RANGE_MASK) | rate_flag
    f[5] = (sensitivity >> 8) & 0xFF
    f[6] = sensitivity & 0xFF
    f[7] = rate
    f[8] = err_count & 0xFF
    f[9] = conv_status & 0xFF
    f[10] = device_status & 0xFF
    return _finish(f)


def encode_error(seq: int, err_code: int, i2c_addr: int = 0, reg_addr: int = 0) -> bytes:
    """编码错误帧。"""
    f = bytearray(FRAME_SIZE)
    f[0] = SYNC
    f[1] = TYPE_ERROR
    f[2] = seq & 0xFF
    f[3] = err_code & 0xFF
    f[4] = i2c_addr & 0xFF
    f[5] = reg_addr & 0xFF
    return _finish(f)


def decode_frame(frame: bytes) -> Optional[Frame]:
    """解码一帧；非法帧返回 None。"""
    if len(frame) != FRAME_SIZE or frame[0] != SYNC:
        return None
    if frame[1] not in (TYPE_DATA, TYPE_STATUS, TYPE_ERROR):
        return None
    if crc8(frame[2:11]) != frame[11]:
        return None

    seq = frame[2]

    if frame[1] == TYPE_DATA:
        x, y, z, t = struct.unpack(">hhhh", frame[3:11])
        return Frame(kind="data", seq=seq, x_raw=x, y_raw=y, z_raw=z, temp_raw=t)

    if frame[1] == TYPE_STATUS:
        version, flags, sensitivity, rate, errcnt, conv, devst = struct.unpack(
            ">BBHBBBB", frame[3:11]
        )
        if version != PROTO_VERSION:
            return None
        return Frame(
            kind="status",
            seq=seq,
            version=version,
            flags=flags,
            range_code=flags & FLAG_RANGE_MASK,
            sensitivity=sensitivity,
            sample_rate_hz=rate * (10 if flags & FLAG_RATE_X10 else 1),
            err_count=errcnt,
            conv_status=conv,
            device_status=devst,
        )

    code = frame[3]
    return Frame(
        kind="error",
        seq=seq,
        err_code=code,
        err_name=ERR_NAMES.get(code, f"UNKNOWN_0x{code:02X}"),
        i2c_addr=frame[4],
        reg_addr=frame[5],
    )


class FrameStream:
    """字节流 → 帧 的增量解析器（处理粘包/拆包/假同步头）。"""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes):
        """喂入字节，产出 (frame, dropped_bytes) 列表。"""
        out = []
        self._buf.extend(chunk)
        while len(self._buf) >= FRAME_SIZE:
            idx = self._buf.find(SYNC)
            if idx < 0:
                dropped = len(self._buf)
                self._buf.clear()
                if dropped:
                    out.append((None, dropped))
                break
            if idx:
                del self._buf[:idx]
                out.append((None, idx))
            if len(self._buf) < FRAME_SIZE:
                break
            candidate = bytes(self._buf[:FRAME_SIZE])
            frame = decode_frame(candidate)
            if frame is None:
                del self._buf[0]
                out.append((None, 1))
                continue
            del self._buf[:FRAME_SIZE]
            out.append((frame, 0))
        return out
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd F:\youko_repo\Tmag3001_for_STM32F4_\host; C:\ProgramData\Anaconda3\python.exe -m pytest`
Expected: **12 passed**（12 个测试函数）。

- [ ] **Step 5: 验证与固件 C 实现的一致性（跨语言 golden vector）**

先在固件侧跑一次协议测试，确认 C 侧同样通过：

Run: `powershell -ExecutionPolicy Bypass -File F:\youko_repo\Tmag3001_for_STM32F4_\tools\hosttest\run_tests.ps1`
Expected: `OK: N/N checks passed`。

> **跨语言一致性是双向的**：Python 的五组 golden vector 是按固件 C 实现同样的规则手算的（CRC 为逐字节 XOR，可直接验算）。若后续有人改动固件的帧布局或 CRC 范围，**必须**同步更新 Python 侧的 golden vector，并在两边同时跑测试。

- [ ] **Step 6: 提交**

```
feat(host): 实现协议层并与固件 golden vector 对齐

protocol.py：12 字节帧编解码 + CRC-8 + FrameStream 增量解析器，
覆盖粘包/拆包/假同步头。零 Qt 依赖，可纯 pytest 测试。

五组 golden vector 与固件 App/Src/tmag_proto.c 逐字节一致，
杜绝固件与 PC 端各自实现漂移。
```

---

### Task B3: 日志模块（Logging_Standard）

**Files:**
- Create: `host/tmag_viewer/log_setup.py`
- Create: `host/tests/test_log_setup.py`

**Interfaces:**
- Consumes: Task B1 骨架
- Produces: `setup_logging(app_name: str, log_dir: str, console_level: int = logging.INFO) -> Path`

- [ ] **Step 1: 先写失败的测试 `host/tests/test_log_setup.py`**

```python
"""日志模块测试：对照 Logging_Standard_for_Agent 的可机器检查条款。"""
from __future__ import annotations

import logging
from pathlib import Path

from tmag_viewer.log_setup import setup_logging


def test_setup_logging_creates_timestamped_file(tmp_path):
    log_path = setup_logging("tmag_viewer", str(tmp_path))
    assert Path(log_path).exists()
    assert Path(log_path).name.startswith("tmag_viewer_")
    assert Path(log_path).suffix == ".log"


def test_setup_logging_installs_file_and_console_handlers(tmp_path):
    setup_logging("tmag_viewer", str(tmp_path))
    root = logging.getLogger()
    kinds = {type(h).__name__ for h in root.handlers}
    assert "RotatingFileHandler" in kinds
    assert "StreamHandler" in kinds


def test_file_handler_is_debug_console_is_info(tmp_path):
    setup_logging("tmag_viewer", str(tmp_path))
    root = logging.getLogger()
    file_h = [h for h in root.handlers if type(h).__name__ == "RotatingFileHandler"][0]
    console_h = [h for h in root.handlers if type(h).__name__ == "StreamHandler"][0]
    assert file_h.level == logging.DEBUG
    assert console_h.level == logging.INFO


def test_file_handler_formatter_has_module_and_lineno(tmp_path):
    setup_logging("tmag_viewer", str(tmp_path))
    root = logging.getLogger()
    file_h = [h for h in root.handlers if type(h).__name__ == "RotatingFileHandler"][0]
    assert "%(name)s:%(lineno)d" in file_h.formatter._fmt
    assert "%(levelname)" in file_h.formatter._fmt


def test_root_level_is_debug(tmp_path):
    setup_logging("tmag_viewer", str(tmp_path))
    assert logging.getLogger().level == logging.DEBUG


def test_setup_logging_is_idempotent(tmp_path):
    setup_logging("tmag_viewer", str(tmp_path))
    first = len(logging.getLogger().handlers)
    setup_logging("tmag_viewer", str(tmp_path))
    assert len(logging.getLogger().handlers) == first
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd F:\youko_repo\Tmag3001_for_STM32F4_\host; C:\ProgramData\Anaconda3\python.exe -m pytest tests\test_log_setup.py`
Expected: `ModuleNotFoundError: No module named 'tmag_viewer.log_setup'`。

- [ ] **Step 3: 写 `host/tmag_viewer/log_setup.py`**

```python
"""日志初始化 —— 严格遵循 Logging_Standard_for_Agent §2。

规则：
- 每次运行生成独立的时间戳文件（File handler = DEBUG）
- 控制台 handler = INFO，只给操作者看干净输出
- 文件 handler 的格式带 %(name)s:%(lineno)d，便于直接跳转源码
- 重复调用会清空旧 handler（GUI 重载场景安全）
"""
from __future__ import annotations

import logging
import logging.handlers
import os
from datetime import datetime
from pathlib import Path


def setup_logging(
    app_name: str = "tmag_viewer",
    log_dir: str = "logs",
    console_level: int = logging.INFO,
) -> Path:
    """配置生产级日志，返回本次运行的日志文件路径。"""
    os.makedirs(log_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = Path(log_dir) / f"{app_name}_{ts}.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    # 文件：DEBUG 级别，模块 + 行号，便于源码导航
    fh = logging.handlers.RotatingFileHandler(
        str(log_path), maxBytes=10 * 1024 * 1024, backupCount=7, encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)-7s] %(name)s:%(lineno)d - %(message)s")
    )
    root.addHandler(fh)

    # 控制台：INFO 级别，精简
    ch = logging.StreamHandler()
    ch.setLevel(console_level)
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)-7s] %(message)s"))
    root.addHandler(ch)

    logging.getLogger(__name__).info("Logging initialized: %s", log_path)
    return log_path
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd F:\youko_repo\Tmag3001_for_STM32F4_\host; C:\ProgramData\Anaconda3\python.exe -m pytest tests\test_log_setup.py`
Expected: **6 passed**。

- [ ] **Step 5: 提交**

```
feat(host): 按 Logging_Standard 实现日志初始化

setup_logging() 严格照搬标准 §2：时间戳文件 handler=DEBUG（带模块:行号）、
控制台 handler=INFO、重复调用清空旧 handler。6 项可机器检查的条款全部有测试。
```

---

### Task B4: 配色模块（UI_palette 思想）

**Files:**
- Create: `host/tmag_viewer/color_scheme.py`
- Create: `host/tests/test_color_scheme.py`

**Interfaces:**
- Consumes: Task B1 骨架
- Produces:
  - `ColorScheme` 类，含类属性 `TEXT/LIGHT/DARK/LINE/BTN/AXIS_X/AXIS_Y/AXIS_Z/TEMP/GRID/AXIS`，以及 `LABEL_SIZE`、`AXIS_LABEL_SIZE`、`LABEL_ALPHA`
  - `ColorScheme.get_stylesheet() -> str`
  - `ColorScheme.hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]`
  - `ColorScheme.adjust(hex_color: str, amount: int) -> str`（派生色计算）
  - `ColorScheme.set_color(role: str, hex_color: str) -> None`
  - `ColorScheme.reset() -> None`

- [ ] **Step 1: 先写失败的测试 `host/tests/test_color_scheme.py`**

```python
"""配色模块测试：对照 UI_palette 的设计决策。"""
from __future__ import annotations

import re

from tmag_viewer.color_scheme import ColorScheme

ROLE_NAMES = [
    "TEXT", "LIGHT", "DARK", "LINE", "BTN",
    "AXIS_X", "AXIS_Y", "AXIS_Z", "TEMP", "GRID", "AXIS",
]


def test_all_roles_present():
    for role in ROLE_NAMES:
        assert isinstance(getattr(ColorScheme, role), str), role
        assert re.fullmatch(r"#[0-9a-fA-F]{6}", getattr(ColorScheme, role)), role


def test_module_has_no_qt_dependency():
    import tmag_viewer.color_scheme as mod
    src = open(mod.__file__, encoding="utf-8").read()
    assert "PyQt5" not in src
    assert "pyqtgraph" not in src


def test_adjust_is_signed_rgb_offset():
    assert ColorScheme.adjust("#000000", +10) == "#0a0a0a"
    assert ColorScheme.adjust("#ffffff", -10) == "#f5f5f5"
    assert ColorScheme.adjust("#808080", 0) == "#808080"


def test_adjust_clamps_to_byte_range():
    assert ColorScheme.adjust("#ffffff", +100) == "#ffffff"
    assert ColorScheme.adjust("#000000", -100) == "#000000"


def test_hex_to_rgba_default_opaque():
    assert ColorScheme.hex_to_rgba("#ff8000") == (255, 128, 0, 255)


def test_hex_to_rgba_with_alpha():
    assert ColorScheme.hex_to_rgba("#ff8000", 60) == (255, 128, 0, 60)


def test_hex_to_rgba_accepts_short_form():
    assert ColorScheme.hex_to_rgba("#f80") == (255, 136, 0, 255)


def test_stylesheet_is_regenerated_not_cached():
    a = ColorScheme.get_stylesheet()
    original = ColorScheme.TEXT
    try:
        ColorScheme.set_color("TEXT", "#ffffff")
        b = ColorScheme.get_stylesheet()
        assert a != b
        assert "#ffffff" in b
    finally:
        ColorScheme.set_color("TEXT", original)


def test_set_color_rejects_unknown_role():
    import pytest
    with pytest.raises(KeyError):
        ColorScheme.set_color("NOT_A_ROLE", "#123456")


def test_reset_restores_defaults():
    original = ColorScheme.TEXT
    try:
        ColorScheme.set_color("TEXT", "#ffffff")
        ColorScheme.reset()
        assert ColorScheme.TEXT == original
    finally:
        ColorScheme.set_color("TEXT", original)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd F:\youko_repo\Tmag3001_for_STM32F4_\host; C:\ProgramData\Anaconda3\python.exe -m pytest tests\test_color_scheme.py`
Expected: `ModuleNotFoundError: No module named 'tmag_viewer.color_scheme'`。

- [ ] **Step 3: 写 `host/tmag_viewer/color_scheme.py`**

```python
"""颜色角色系统 —— 借鉴 UI_palette 的设计决策。

关键决策（沿用 UI_palette）：
- 颜色用**类属性**而不是字典：QSS 的 f-string 可以直接写 ColorScheme.TEXT
- get_stylesheet() 是**函数**而不是文件：每次调用重新读取类属性，始终反映当前状态
- 派生色由 adjust() 内联计算（对 RGB 各分量加一个有符号整数）
- 本模块**零 Qt 导入**，可独立测试
"""
from __future__ import annotations

# 角色默认值：基础 5 + 曲线 4 + 显示 2
_DEFAULTS: dict[str, str] = {
    # 基础
    "TEXT": "#c0caf5",
    "LIGHT": "#1e1f2e",
    "DARK": "#1a1b26",
    "LINE": "#3b3d56",
    "BTN": "#3b3d56",
    # 曲线
    "AXIS_X": "#f7768e",
    "AXIS_Y": "#9ece6a",
    "AXIS_Z": "#7aa2f7",
    "TEMP": "#e0af68",
    # 显示
    "GRID": "#2c2d3f",
    "AXIS": "#565f89",
}


def _clamp8(v: int) -> int:
    return 0 if v < 0 else (255 if v > 255 else v)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    if len(v) == 3:
        v = "".join(ch * 2 for ch in v)
    if len(v) != 6:
        raise ValueError(f"bad hex color: {value!r}")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


class ColorScheme:
    """颜色角色的唯一真相源。"""

    # ── 基础色 ──
    TEXT = _DEFAULTS["TEXT"]
    LIGHT = _DEFAULTS["LIGHT"]
    DARK = _DEFAULTS["DARK"]
    LINE = _DEFAULTS["LINE"]
    BTN = _DEFAULTS["BTN"]

    # ── 曲线色 ──
    AXIS_X = _DEFAULTS["AXIS_X"]
    AXIS_Y = _DEFAULTS["AXIS_Y"]
    AXIS_Z = _DEFAULTS["AXIS_Z"]
    TEMP = _DEFAULTS["TEMP"]

    # ── 显示色 ──
    GRID = _DEFAULTS["GRID"]
    AXIS = _DEFAULTS["AXIS"]

    # ── 可调常量 ──
    LABEL_SIZE = 14        # 图表标签字体像素
    AXIS_LABEL_SIZE = 13   # 坐标轴刻度字体像素
    LABEL_ALPHA = "ff"     # 标签背景不透明度（十六进制字符串）

    ROLES = tuple(_DEFAULTS.keys())

    # ── 工具 ──

    @classmethod
    def adjust(cls, hex_color: str, amount: int) -> str:
        """派生色：对 RGB 各分量加一个有符号整数，结果钳位到 [0,255]。"""
        r, g, b = _hex_to_rgb(hex_color)
        return _rgb_to_hex((_clamp8(r + amount), _clamp8(g + amount), _clamp8(b + amount)))

    @classmethod
    def hex_to_rgba(cls, hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
        """给 pyqtgraph 的 mkPen/mkBrush 用。"""
        r, g, b = _hex_to_rgb(hex_color)
        return r, g, b, alpha

    @classmethod
    def set_color(cls, role: str, hex_color: str) -> None:
        """修改一个角色的颜色。未知角色抛 KeyError。"""
        if role not in _DEFAULTS:
            raise KeyError(role)
        _hex_to_rgb(hex_color)          # 校验格式
        setattr(cls, role, hex_color)

    @classmethod
    def reset(cls) -> None:
        """恢复全部默认颜色。"""
        for role, value in _DEFAULTS.items():
            setattr(cls, role, value)

    @classmethod
    def snapshot(cls) -> dict[str, str]:
        """当前全部颜色的快照（用于设置持久化）。"""
        return {role: getattr(cls, role) for role in cls.ROLES}

    # ── 派生色（随基础色联动）──
    @property
    def text2(self) -> str:
        return self.adjust(self.TEXT, -30)

    @property
    def text3(self) -> str:
        return self.adjust(self.TEXT, -50)

    @property
    def dark2(self) -> str:
        return self.adjust(self.DARK, -6)

    @property
    def accent(self) -> str:
        return self.adjust(self.LIGHT, +30)

    @property
    def btn_hover(self) -> str:
        return self.adjust(self.BTN, +10)

    # ── QSS 生成 ──

    @classmethod
    def get_stylesheet(cls) -> str:
        """生成完整 QSS。每次调用都重新读取类属性，因此改色立即生效。"""
        s = cls()
        return f"""
QWidget {{ background-color: {cls.DARK}; color: {cls.TEXT}; }}
QMainWindow {{ background-color: {cls.DARK}; }}
QGroupBox {{
    border: 1px solid {cls.LINE};
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 8px;
    background-color: {cls.LIGHT};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {s.accent};
}}
QLabel {{ color: {s.text2}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {s.dark2};
    border: 1px solid {cls.LINE};
    border-radius: 3px;
    padding: 2px 4px;
    color: {cls.TEXT};
}}
QPushButton {{
    background-color: {cls.BTN};
    border: 1px solid {cls.LINE};
    border-radius: 3px;
    padding: 4px 10px;
    color: {cls.TEXT};
}}
QPushButton:hover {{ background-color: {s.btn_hover}; }}
QPushButton:pressed {{ background-color: {s.dark2}; }}
QPushButton:disabled {{ color: {s.text3}; }}
QPlainTextEdit {{
    background-color: {cls.DARK};
    border: 1px solid {cls.LINE};
    color: {cls.TEXT};
    font-family: Consolas, monospace;
}}
QStatusBar {{ color: {s.text2}; background-color: {cls.DARK}; }}
QScrollBar:vertical {{ background: {cls.LIGHT}; width: 10px; }}
QScrollBar::handle:vertical {{ background: {cls.LINE}; border-radius: 5px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QSplitter::handle {{ background-color: {cls.LINE}; }}
""".strip()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd F:\youko_repo\Tmag3001_for_STM32F4_\host; C:\ProgramData\Anaconda3\python.exe -m pytest tests\test_color_scheme.py`
Expected: **10 passed**。

- [ ] **Step 5: 提交**

```
feat(host): 颜色角色系统（UI_palette 设计决策）

- ColorScheme 用类属性作唯一真相源，零 Qt 导入，可独立测试
- get_stylesheet() 是函数，每次重读属性；派生色由 adjust() 内联计算
- 11 个角色：基础 5 + 曲线 4（X/Y/Z/TEMP）+ 显示 2
- 10 项测试覆盖角色完整性、派生色钳位、hex_to_rgba、样式即时再生
```

---

### Task B5: 设置持久化（JSON + 原子写）

**Files:**
- Create: `host/tmag_viewer/settings_manager.py`
- Create: `host/tests/test_settings_manager.py`

**Interfaces:**
- Consumes: Task B1 骨架、Task B4 的 `ColorScheme`
- Produces:
  - `DEFAULTS: dict`
  - `get_settings_path() -> Path`
  - `load_settings() -> dict`（深度合并，未知键保留）
  - `save_settings(data: dict) -> None`（原子写）

- [ ] **Step 1: 先写失败的测试 `host/tests/test_settings_manager.py`**

```python
"""设置持久化测试。"""
from __future__ import annotations

import json

import pytest

from tmag_viewer import settings_manager as S


def test_load_returns_defaults_when_file_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "get_settings_path", lambda: tmp_path / "settings.json")
    data = S.load_settings()
    assert data["panels"]["right"] is True
    assert data["colors"]["TEXT"] == "#c0caf5"


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "get_settings_path", lambda: tmp_path / "settings.json")
    S.save_settings({"panels": {"right": False}})
    data = S.load_settings()
    assert data["panels"]["right"] is False
    # 未写到的段仍用默认值
    assert data["panels"]["log"] is True


def test_save_is_atomic_no_temp_left(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "get_settings_path", lambda: tmp_path / "settings.json")
    S.save_settings({"panels": {"right": False}})
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "settings.json"]
    assert leftovers == []


def test_unknown_keys_are_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "get_settings_path", lambda: tmp_path / "settings.json")
    (tmp_path / "settings.json").write_text(
        json.dumps({"future_feature": {"x": 1}}), encoding="utf-8"
    )
    data = S.load_settings()
    assert data["future_feature"] == {"x": 1}


def test_malformed_section_falls_back_to_default(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "get_settings_path", lambda: tmp_path / "settings.json")
    (tmp_path / "settings.json").write_text("{not json", encoding="utf-8")
    data = S.load_settings()
    assert data["panels"]["right"] is True


def test_defaults_are_deep_copied(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "get_settings_path", lambda: tmp_path / "settings.json")
    a = S.load_settings()
    a["colors"]["TEXT"] = "#ffffff"
    b = S.load_settings()
    assert b["colors"]["TEXT"] == "#c0caf5"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd F:\youko_repo\Tmag3001_for_STM32F4_\host; C:\ProgramData\Anaconda3\python.exe -m pytest tests\test_settings_manager.py`
Expected: `ModuleNotFoundError: No module named 'tmag_viewer.settings_manager'`。

- [ ] **Step 3: 写 `host/tmag_viewer/settings_manager.py`**

```python
"""设置持久化 —— 借鉴 UI_palette 的 settings_manager。

- 深度合并：缺失的键取默认值，未知键保留
- 原子写：tmp 文件 + os.replace，中断不会留下半截文件
"""
from __future__ import annotations

import copy
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from tmag_viewer.color_scheme import ColorScheme

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "colors": {
        "TEXT": ColorScheme.TEXT,
        "LIGHT": ColorScheme.LIGHT,
        "DARK": ColorScheme.DARK,
        "LINE": ColorScheme.LINE,
        "BTN": ColorScheme.BTN,
        "AXIS_X": ColorScheme.AXIS_X,
        "AXIS_Y": ColorScheme.AXIS_Y,
        "AXIS_Z": ColorScheme.AXIS_Z,
        "TEMP": ColorScheme.TEMP,
        "GRID": ColorScheme.GRID,
        "AXIS": ColorScheme.AXIS,
    },
    "panels": {"left": True, "right": True, "log": True},
    "acquisition": {
        "port": "",
        "baud": 115200,
        "kalman": False,
        "sample_rate_hz": 0,
    },
    "chart_labels": {},
}


def get_settings_path() -> Path:
    """设置文件位置：源码目录旁（冻结成 exe 时是 sys.executable 旁）。"""
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return base / "settings.json"


def _deep_merge(base: dict, override: dict) -> dict:
    """override 覆盖 base；未知键保留；嵌套 dict 递归合并。"""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_settings() -> dict:
    """读取设置并与默认值深度合并。任何异常都回退到默认值。"""
    path = get_settings_path()
    defaults = copy.deepcopy(DEFAULTS)
    if not path.exists():
        return defaults
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("设置文件读取失败: %s (%s)", path, exc)
        return defaults
    if not isinstance(raw, dict):
        logger.error("设置文件格式不是对象: %s", path)
        return defaults
    return _deep_merge(defaults, raw)


def save_settings(data: dict) -> None:
    """原子写入设置文件。"""
    path = get_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp), str(path))
        logger.info("FILE_IO | op=rename kind=config path=%s -> %s", tmp, path)
    except Exception:
        logger.exception("FILE_IO | op=write kind=config path=%s FAILED", path)
        if tmp.exists():
            tmp.unlink()
        raise
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd F:\youko_repo\Tmag3001_for_STM32F4_\host; C:\ProgramData\Anaconda3\python.exe -m pytest tests\test_settings_manager.py`
Expected: **6 passed**。

- [ ] **Step 5: 提交**

```
feat(host): 设置持久化（深度合并 + 原子写）

借鉴 UI_palette 的 settings_manager：深度合并、未知键保留、格式错误回退默认、
tmp + os.replace 原子写（无临时文件残留）。
```

---

### Task B6: 串口采集线程

**Files:**
- Create: `host/tmag_viewer/serial_source.py`
- Create: `host/tmag_viewer/csv_writer.py`
- Create: `host/tests/test_csv_writer.py`

**Interfaces:**
- Consumes: Task B2 的 `protocol.py`
- Produces:
  - `SerialSource(QObject)`，信号：`sample_received(object)`、`status_received(object)`、`error_received(object)`、`stats_updated(dict)`、`connection_changed(bool)`
  - `SerialSource.open(port: str, baud: int) -> bool` / `close()`
  - `SerialSource.stats` → dict（`frames`、`dropped`、`rate_hz`、`errors`、`last_seq`）
  - `CsvWriter(path)`：`.open()`、`.write(x, y, z, t)`、`.close()`（原子替换）

- [ ] **Step 1: 先写失败的测试 `host/tests/test_csv_writer.py`**

```python
"""CSV 原子写测试。"""
from __future__ import annotations

import csv

from tmag_viewer.csv_writer import CsvWriter


def test_write_then_read_back(tmp_path):
    p = tmp_path / "data.csv"
    w = CsvWriter(p)
    w.open()
    w.write(1.0, 2.0, 3.0, 25.5)
    w.close()
    rows = list(csv.reader(p.read_text(encoding="utf-8").splitlines()))
    assert rows[0] == ["X_mT", "Y_mT", "Z_mT", "T_C"]
    assert len(rows) == 2
    assert rows[1][0] == "1.0000"


def test_no_partial_file_after_close(tmp_path):
    p = tmp_path / "data.csv"
    w = CsvWriter(p)
    w.open()
    w.write(1.0, 2.0, 3.0, 25.5)
    w.close()
    leftovers = [x.name for x in tmp_path.iterdir() if x.name != "data.csv"]
    assert leftovers == []


def test_temp_file_exists_while_open(tmp_path):
    p = tmp_path / "data.csv"
    w = CsvWriter(p)
    w.open()
    w.write(1.0, 2.0, 3.0, 25.5)
    # 保存过程中目标文件还不存在，只有 tmp
    assert not p.exists()
    w.close()
    assert p.exists()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd F:\youko_repo\Tmag3001_for_STM32F4_\host; C:\ProgramData\Anaconda3\python.exe -m pytest tests\test_csv_writer.py`
Expected: `ModuleNotFoundError: No module named 'tmag_viewer.csv_writer'`。

- [ ] **Step 3: 写 `host/tmag_viewer/csv_writer.py`**

```python
"""CSV 采集数据保存 —— 遵循 Logging_Standard §18 的原子写要求。

写入期间只写 tmp 文件，close() 时才 os.replace 到目标路径，
因此中途退出不会留下半截的正式文件。
"""
from __future__ import annotations

import csv
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

HEADER = ["X_mT", "Y_mT", "Z_mT", "T_C"]


class CsvWriter:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._tmp: Path | None = None
        self._fh = None
        self._writer = None
        self._rows = 0

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".tmag-", suffix=".tmp", dir=str(self.path.parent)
        )
        self._tmp = Path(tmp_name)
        self._fh = os.fdopen(fd, "w", encoding="utf-8", newline="")
        self._writer = csv.writer(self._fh)
        self._writer.writerow(HEADER)
        self._rows = 0
        logger.info("FILE_IO | op=open kind=data path=%s", self._tmp)

    def write(self, x: float, y: float, z: float, t: float) -> None:
        if self._writer is None:
            return
        self._writer.writerow([f"{x:.4f}", f"{y:.4f}", f"{z:.4f}", f"{t:.4f}"])
        self._rows += 1

    def close(self) -> None:
        if self._fh is None:
            return
        try:
            self._fh.flush()
            os.fsync(self._fh.fileno())
        except OSError as exc:
            logger.exception("FILE_IO | op=fsync kind=data path=%s FAILED", self.path)
            raise
        finally:
            self._fh.close()
            self._fh = None
        if self._tmp is not None:
            os.replace(str(self._tmp), str(self.path))
            logger.info(
                "FILE_IO | op=rename kind=data path=%s -> %s rows=%d",
                self._tmp, self.path, self._rows,
            )
            self._tmp = None
        self._writer = None
```

- [ ] **Step 4: 写 `host/tmag_viewer/serial_source.py`**

```python
"""串口采集线程。

- QThread 后台读串口，解析 12 字节帧，通过 Qt 信号送回主线程
- 日志一律带 [transport=serial][addr=COM9@115200] 标签
- 采样回调（>100Hz 路径）**不打日志**，只累加计数；日志按周期汇总
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal

from tmag_viewer import protocol as P

logger = logging.getLogger(__name__)


class SerialSource(QObject):
    sample_received = pyqtSignal(object)
    status_received = pyqtSignal(object)
    error_received = pyqtSignal(object)
    stats_updated = pyqtSignal(dict)
    connection_changed = pyqtSignal(bool)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._thread: Optional[QThread] = None
        self._stop = threading.Event()
        self._port = ""
        self._baud = 115200
        self._seq: Optional[int] = None
        self._frames = 0
        self._dropped = 0
        self._errors = 0
        self._samples = 0
        self._t0 = 0.0

    # ── 状态 ──
    @property
    def stats(self) -> dict:
        elapsed = max(time.monotonic() - self._t0, 1e-9) if self._t0 else 0.0
        return {
            "frames": self._frames,
            "samples": self._samples,
            "dropped": self._dropped,
            "errors": self._errors,
            "rate_hz": self._samples / elapsed if elapsed else 0.0,
            "last_seq": self._seq,
        }

    # ── 控制 ──
    def open(self, port: str, baud: int = 115200) -> bool:
        self.close()
        self._port = port
        self._baud = baud
        self._stop.clear()
        self._thread = QThread()
        self._thread.started.connect(self._run)
        self._thread.start()
        logger.info(
            "[transport=serial][addr=%s@%d] 连接已发起", port, baud
        )
        self.connection_changed.emit(True)
        return True

    def close(self) -> None:
        if self._thread is not None:
            self._stop.set()
            self._thread.quit()
            self._thread.wait(2000)
            self._thread = None
            logger.info("[transport=serial][addr=%s@%d] 已断开", self._port, self._baud)
            self.connection_changed.emit(False)

    # ── 采集循环 ──
    def _run(self) -> None:
        try:
            import serial
        except ImportError:
            logger.error("pyserial 未安装")
            return

        stream = P.FrameStream()
        self._t0 = time.monotonic()
        try:
            ser = serial.Serial(self._port, self._baud, timeout=0.2)
        except Exception as exc:
            logger.error("[transport=serial][addr=%s@%d] 打开失败: %s",
                         self._port, self._baud, exc)
            self.connection_changed.emit(False)
            return

        try:
            while not self._stop.is_set():
                try:
                    chunk = ser.read(ser.in_waiting or 1)
                except Exception as exc:
                    logger.error("[transport=serial][addr=%s@%d] 读取失败: %s",
                                 self._port, self._baud, exc)
                    break
                if not chunk:
                    continue
                for frame, dropped in stream.feed(chunk):
                    if dropped:
                        self._dropped += dropped
                    if frame is None:
                        continue
                    self._frames += 1
                    if self._seq is not None:
                        expected = (self._seq + 1) & 0xFF
                        if frame.seq != expected:
                            self._dropped += (frame.seq - expected) & 0xFF
                    self._seq = frame.seq
                    if frame.kind == "data":
                        self._samples += 1
                        self.sample_received.emit(frame)
                    elif frame.kind == "status":
                        self.status_received.emit(frame)
                    elif frame.kind == "error":
                        self._errors += 1
                        if frame.err_code != P.ERR_NONE:
                            logger.warning(
                                "[transport=serial][addr=%s@%d] 错误帧 code=0x%02X name=%s",
                                self._port, self._baud, frame.err_code, frame.err_name,
                            )
                        self.error_received.emit(frame)
        finally:
            try:
                ser.close()
            except Exception:
                pass
            self.connection_changed.emit(False)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd F:\youko_repo\Tmag3001_for_STM32F4_\host; C:\ProgramData\Anaconda3\python.exe -m pytest`
Expected: 全部通过（协议 12 + 日志 6 + 配色 10 + 设置 6 + CSV 3 = **37 passed**）。

- [ ] **Step 6: 提交**

```
feat(host): 串口采集线程与 CSV 原子写

- SerialSource：QThread 读串口 + FrameStream 增量解析 + 丢帧/速率统计，
  日志带 [transport=serial][addr=...] 标签，高频采样路径不打日志
- CsvWriter：tmp + fsync + os.replace，保存期间正式文件不出现
```

---

### Task B7: 图表组件

**Files:**
- Create: `host/tmag_viewer/plot_widgets.py`

**Interfaces:**
- Consumes: Task B2 的 `protocol.py`、Task B4 的 `color_scheme.py`
- Produces:
  - `MagPlotWidget(pg.GraphicsLayoutWidget)`：主图 XYZ 三曲线叠加 + 副图温度；共享时间轴
  - `.push_sample(x_mt, y_mt, z_mt, temp_c)` —— 追加一点
  - `.clear()` —— 清空缓冲
  - `.set_max_points(n)`
  - `.apply_theme()` —— 按 ColorScheme 重刷背景/网格/坐标轴/画笔

- [ ] **Step 1: 写 `host/tmag_viewer/plot_widgets.py`**

```python
"""pyqtgraph 图表组件。

- 主图：X/Y/Z 三通道叠加（共享时间轴，便于同时刻对比）
- 副图：温度
- 缓冲区用 deque，滚动窗口；setData 只在更新时调用（热路径不做分配）
- 主题来自 ColorScheme，apply_theme() 可即时换色
"""
from __future__ import annotations

import logging
from collections import deque

import pyqtgraph as pg
from PyQt5.QtWidgets import QVBoxLayout, QWidget

from tmag_viewer.color_scheme import ColorScheme

logger = logging.getLogger(__name__)

MAX_POINTS = 2000


class MagPlotWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._canvas = pg.GraphicsLayoutWidget()
        layout.addWidget(self._canvas)

        self._max_points = MAX_POINTS
        self._t = deque(maxlen=self._max_points)
        self._x = deque(maxlen=self._max_points)
        self._y = deque(maxlen=self._max_points)
        self._z = deque(maxlen=self._max_points)
        self._temp = deque(maxlen=self._max_points)
        self._index = 0

        self._plot_xyz = self._canvas.addPlot(row=0, col=0, title="三轴磁场")
        self._plot_temp = self._canvas.addPlot(row=1, col=0, title="温度")

        self._curve_x = self._plot_xyz.plot(pen=pg.mkPen(width=2), name="X")
        self._curve_y = self._plot_xyz.plot(pen=pg.mkPen(width=2), name="Y")
        self._curve_z = self._plot_xyz.plot(pen=pg.mkPen(width=2), name="Z")
        self._curve_temp = self._plot_temp.plot(pen=pg.mkPen(width=2), name="T")

        self._plot_xyz.setLabel("bottom", "Sample", units="n")
        self._plot_xyz.setLabel("left", "mT")
        self._plot_temp.setLabel("bottom", "Sample", units="n")
        self._plot_temp.setLabel("left", "°C")
        self._plot_temp.setXLink(self._plot_xyz)

        self.apply_theme()

    # ── 数据 ──
    def set_max_points(self, n: int) -> None:
        n = max(10, int(n))
        if n == self._max_points:
            return
        self._max_points = n
        for d in (self._t, self._x, self._y, self._z, self._temp):
            d.clear()
            d.extend([0] * 0)
        self._t = deque(self._t, maxlen=n)
        self._x = deque(self._x, maxlen=n)
        self._y = deque(self._y, maxlen=n)
        self._z = deque(self._z, maxlen=n)
        self._temp = deque(self._temp, maxlen=n)
        self._index = 0
        self._refresh()

    def push_sample(self, x_mt: float, y_mt: float, z_mt: float, temp_c: float) -> None:
        self._t.append(self._index)
        self._x.append(x_mt)
        self._y.append(y_mt)
        self._z.append(z_mt)
        self._temp.append(temp_c)
        self._index += 1

    def clear(self) -> None:
        for d in (self._t, self._x, self._y, self._z, self._temp):
            d.clear()
        self._index = 0
        self._refresh()

    # ── 渲染 ──
    def _refresh(self) -> None:
        t = list(self._t)
        self._curve_x.setData(t, list(self._x))
        self._curve_y.setData(t, list(self._y))
        self._curve_z.setData(t, list(self._z))
        self._curve_temp.setData(t, list(self._temp))

    def refresh(self) -> None:
        """由主窗口的定时器调用（不在采样热路径里刷新）。"""
        self._refresh()

    # ── 主题 ──
    def apply_theme(self) -> None:
        cs = ColorScheme
        self._canvas.setBackground(cs.DARK)
        for plot in (self._plot_xyz, self._plot_temp):
            plot.showGrid(x=True, y=True, alpha=0.25)
            plot.getAxis("left").setPen(pg.mkPen(cs.AXIS))
            plot.getAxis("bottom").setPen(pg.mkPen(cs.AXIS))
            plot.getAxis("left").setTextPen(pg.mkPen(cs.AXIS))
            plot.getAxis("bottom").setTextPen(pg.mkPen(cs.AXIS))
            plot.setTitle(color=cs.TEXT)
        self._curve_x.setPen(pg.mkPen(cs.AXIS_X, width=2))
        self._curve_y.setPen(pg.mkPen(cs.AXIS_Y, width=2))
        self._curve_z.setPen(pg.mkPen(cs.AXIS_Z, width=2))
        self._curve_temp.setPen(pg.mkPen(cs.TEMP, width=2))
```

- [ ] **Step 2: 冒烟验证（不写正式测试，用 offscreen 跑一次）**

在 `host/` 下创建临时脚本 `host/_smoke_plot.py`：

```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication
app = QApplication([])
from tmag_viewer.plot_widgets import MagPlotWidget
w = MagPlotWidget()
for i in range(100):
    w.push_sample(i * 0.1, -i * 0.05, 0.3 * i, 25.0 + i * 0.01)
w.refresh()
w.apply_theme()
print("plot smoke OK")
```

Run: `cd F:\youko_repo\Tmag3001_for_STM32F4_\host; C:\ProgramData\Anaconda3\python.exe _smoke_plot.py`
Expected: 打印 `plot smoke OK`（QFontDatabase 的字体警告可忽略）。

- [ ] **Step 3: 提交**

```
feat(host): pyqtgraph 图表组件

主图 XYZ 三通道叠加 + 温度副图，共享时间轴；deque 滚动缓冲；
apply_theme() 按 ColorScheme 重刷背景/网格/坐标轴/画笔。
```

---

### Task B8: 颜色面板与主窗口

**Files:**
- Create: `host/tmag_viewer/color_panel.py`
- Create: `host/tmag_viewer/main_window.py`
- Modify: `host/run.py`（接入 QSS 与主窗口）

**Interfaces:**
- Consumes: Task B4 `color_scheme`、B5 `settings_manager`、B6 `serial_source`、B7 `plot_widgets`
- Produces: `MainWindow(QMainWindow)`，可运行的应用窗口

- [ ] **Step 1: 写 `host/tmag_viewer/color_panel.py`**

```python
"""颜色角色编辑面板 —— 借鉴 UI_palette 的 color_panel。

170px 右侧边栏，3 个区域（基础色 / 曲线色 / 显示色）+ 重置按钮。
每行：色块 + 角色名 + 十六进制输入框 + 取色按钮。
"""
from __future__ import annotations

import logging

from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QColorDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from tmag_viewer.color_scheme import ColorScheme

logger = logging.getLogger(__name__)

SECTIONS = [
    ("基础色", ["TEXT", "LIGHT", "DARK", "LINE", "BTN"]),
    ("曲线色", ["AXIS_X", "AXIS_Y", "AXIS_Z", "TEMP"]),
    ("显示色", ["GRID", "AXIS"]),
]


class ColorRow(QWidget):
    def __init__(self, role: str, on_change, parent=None) -> None:
        super().__init__(parent)
        self.role = role
        self._on_change = on_change
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 1, 2, 1)

        self._swatch = QLabel()
        self._swatch.setFixedSize(14, 14)
        row.addWidget(self._swatch)

        name = QLabel(role)
        name.setFixedWidth(56)
        row.addWidget(name)

        self._edit = QLineEdit(getattr(ColorScheme, role))
        self._edit.setFixedWidth(72)
        self._edit.returnPressed.connect(self._apply_text)
        row.addWidget(self._edit)

        pick = QPushButton("…")
        pick.setFixedWidth(24)
        pick.clicked.connect(self._pick)
        row.addWidget(pick)

        self._refresh_swatch()

    def _refresh_swatch(self) -> None:
        color = QColor(getattr(ColorScheme, self.role))
        self._swatch.setStyleSheet(
            f"background-color: {color.name()}; border: 1px solid #555555;"
        )
        self._edit.setText(getattr(ColorScheme, self.role))

    def _apply_text(self) -> None:
        text = self._edit.text().strip()
        if not text.startswith("#") or len(text) not in (4, 7):
            self._edit.setStyleSheet("border: 1px solid #e74c3c;")
            return
        try:
            ColorScheme.set_color(self.role, text)
        except (KeyError, ValueError):
            self._edit.setStyleSheet("border: 1px solid #e74c3c;")
            return
        self._edit.setStyleSheet("")
        self._refresh_swatch()
        self._on_change(self.role)

    def _pick(self) -> None:
        current = QColor(getattr(ColorScheme, self.role))
        chosen = QColorDialog.getColor(current, self, f"选择 {self.role}")
        if chosen.isValid():
            ColorScheme.set_color(self.role, chosen.name())
            self._refresh_swatch()
            self._on_change(self.role)


class ColorPanel(QWidget):
    def __init__(self, on_change=None, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(170)
        self._on_change = on_change or (lambda role: None)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        for title, roles in SECTIONS:
            box = QGroupBox(title)
            inner = QVBoxLayout(box)
            for role in roles:
                inner.addWidget(ColorRow(role, self._on_change))
            layout.addWidget(box)

        reset = QPushButton("重置")
        reset.clicked.connect(self._reset)
        layout.addWidget(reset)
        layout.addStretch()

    def _reset(self) -> None:
        ColorScheme.reset()
        self._on_change("__reset__")
```

- [ ] **Step 2: 写 `host/tmag_viewer/main_window.py`**

```python
"""主窗口 —— 借鉴 UI_palette 的 main_window 布局编排。

布局：
  顶部  控制面板（串口 / 波特率 / 连接 / 保存 / 清屏 / Kalman）
  中部  图表（XYZ 叠加 + 温度）
  右侧  颜色面板（可折叠）
  底部  日志面板（可折叠）
  状态栏 连接 / 传感器 / SEQ / 丢帧 / 帧率 / 量程

日志遵循 Logging_Standard：模块 logger、HEALTH 行、禁用 f-string。
"""
from __future__ import annotations

import logging
import time

from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAction, QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
    QMainWindow, QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from tmag_viewer import protocol as P
from tmag_viewer.color_panel import ColorPanel
from tmag_viewer.color_scheme import ColorScheme
from tmag_viewer.csv_writer import CsvWriter
from tmag_viewer.plot_widgets import MagPlotWidget
from tmag_viewer.serial_source import SerialSource
from tmag_viewer.settings_manager import load_settings, save_settings

logger = logging.getLogger(__name__)

HEALTH_PERIOD_S = 30


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TMAG3001 磁场实时可视化")
        self.resize(1280, 820)

        self._settings = load_settings()
        self._csv: CsvWriter | None = None
        self._sensitivity = 0          # 只来自状态帧，禁止硬编码
        self._range_name = "-"
        self._sample_rate_hz = 0
        self._t_start = time.monotonic()
        self._rss_prev = 0.0
        self._warned_clock = False

        self._source = SerialSource(self)
        self._source.sample_received.connect(self._on_sample)
        self._source.status_received.connect(self._on_status)
        self._source.error_received.connect(self._on_error)
        self._source.stats_updated.connect(self._on_stats)

        self._build_ui()
        self._apply_theme()
        self._restore_settings()

        self._chart_timer = QTimer(self)
        self._chart_timer.timeout.connect(self._refresh_chart)
        self._chart_timer.start(33)

        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._update_stats)
        self._stats_timer.start(1000)

        self._health_timer = QTimer(self)
        self._health_timer.timeout.connect(self._log_health)
        self._health_timer.start(HEALTH_PERIOD_S * 1000)

        logger.info("主窗口就绪")

    # ── UI 构建 ──
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        # 控制面板
        ctrl = QGroupBox("控制")
        ctrl_row = QHBoxLayout(ctrl)

        self._port_combo = QComboBox()
        self._port_combo.setMinimumWidth(90)
        ctrl_row.addWidget(QLabel("串口:"))
        ctrl_row.addWidget(self._port_combo)

        refresh = QPushButton("刷新")
        refresh.clicked.connect(self._refresh_ports)
        ctrl_row.addWidget(refresh)

        self._connect_btn = QPushButton("连接")
        self._connect_btn.clicked.connect(self._toggle_connection)
        ctrl_row.addWidget(self._connect_btn)

        self._baud_combo = QComboBox()
        self._baud_combo.addItems(["115200", "230400", "460800", "921600"])
        self._baud_combo.setCurrentText("115200")
        ctrl_row.addWidget(QLabel("波特率:"))
        ctrl_row.addWidget(self._baud_combo)

        self._save_btn = QPushButton("保存 CSV")
        self._save_btn.clicked.connect(self._toggle_csv)
        ctrl_row.addWidget(self._save_btn)

        clear_btn = QPushButton("清屏")
        clear_btn.clicked.connect(self._clear)
        ctrl_row.addWidget(clear_btn)

        self._kalman_cb = QCheckBox("Kalman")
        ctrl_row.addWidget(self._kalman_cb)

        ctrl_row.addStretch()
        outer.addWidget(ctrl)

        # 状态栏
        status_row = QHBoxLayout()
        self._status_label = QLabel("未连接")
        self._sensor_label = QLabel("传感器: 未知")
        self._seq_label = QLabel("SEQ: -")
        self._drop_label = QLabel("丢帧: 0")
        self._rate_label = QLabel("0.0 Hz")
        self._range_label = QLabel("量程: -")
        status_row.addWidget(self._status_label)
        status_row.addStretch()
        status_row.addWidget(self._sensor_label)
        status_row.addWidget(self._range_label)
        status_row.addWidget(self._seq_label)
        status_row.addWidget(self._drop_label)
        status_row.addWidget(self._rate_label)
        outer.addLayout(status_row)

        # 主体：图表 | 颜色面板
        body = QSplitter(Qt_Horizontal := 1)  # Qt.Horizontal
        self._plot = MagPlotWidget()
        body.addWidget(self._plot)
        self._color_panel = ColorPanel(on_change=self._on_color_changed)
        body.addWidget(self._color_panel)
        body.setStretchFactor(0, 1)
        body.setStretchFactor(1, 0)
        outer.addWidget(body, stretch=1)

        # 日志面板
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(500)
        self._log_view.setMaximumHeight(150)
        outer.addWidget(self._log_view)

        self._statusBar().showMessage("就绪")

        # 快捷键
        full = QAction("全屏", self)
        full.setShortcut(QKeySequence("F10"))
        full.triggered.connect(self._toggle_fullscreen)
        self.addAction(full)

        esc = QAction("退出全屏", self)
        esc.setShortcut(QKeySequence("Esc"))
        esc.triggered.connect(self._exit_fullscreen)
        self.addAction(esc)

        self._refresh_ports()

    # ── 串口 ──
    def _refresh_ports(self) -> None:
        try:
            import serial.tools.list_ports as list_ports
        except ImportError:
            return
        current = self._port_combo.currentText()
        self._port_combo.clear()
        for port in list_ports.comports():
            self._port_combo.addItem(port.device)
        if current:
            self._port_combo.setCurrentText(current)

    def _toggle_connection(self) -> None:
        if self._source.stats["frames"] and not self._connected:
            pass
        if self._connected:
            self._source.close()
            self._connected = False
            self._connect_btn.setText("连接")
            self._status_label.setText("未连接")
        else:
            port = self._port_combo.currentText()
            if not port:
                self._log_view.appendPlainText("请先选择串口")
                return
            baud = int(self._baud_combo.currentText())
            self._source.open(port, baud)
            self._connected = True
            self._connect_btn.setText("断开")
            self._status_label.setText(f"已连接 {port} @ {baud}")
            logger.info(
                "[transport=serial][addr=%s@%d] 已连接", port, baud
            )

    # ── 帧回调 ──
    def _on_sample(self, frame) -> None:
        if self._sensitivity <= 0:
            return          # 未拿到状态帧前不显示数值（禁止硬编码灵敏度）
        x = frame.to_mt(frame.x_raw, self._sensitivity)
        y = frame.to_mt(frame.y_raw, self._sensitivity)
        z = frame.to_mt(frame.z_raw, self._sensitivity)
        temp_c = (frame.temp_raw - 17512.0) / 58.2 + 25.0
        self._plot.push_sample(x, y, z, temp_c)
        if self._csv is not None:
            self._csv.write(x, y, z, temp_c)

    def _on_status(self, frame) -> None:
        self._sensitivity = frame.sensitivity
        self._range_name = frame.range_name
        self._sample_rate_hz = frame.sample_rate_hz
        self._sensor_label.setText(
            "传感器: " + ("就绪" if frame.sensor_ready else "未就绪")
        )
        self._range_label.setText(
            f"量程: {frame.range_name} ({frame.sensitivity} LSB/mT)"
        )
        self._seq_label.setText(f"SEQ: {frame.seq}")
        if not frame.int_path_ok:
            self._log_view.appendPlainText(
                "[警告] 传感器 INT 中断路径未生效，已退化为轮询"
            )
        if not frame.clock_from_hse and not self._warned_clock:
            self._warned_clock = True
            self._log_view.appendPlainText(
                "[警告] 固件未使用 25MHz 晶振（已回退内部 RC），时钟精度受限"
            )

    def _on_error(self, frame) -> None:
        if frame.err_code == P.ERR_NONE:
            return
        self._log_view.appendPlainText(f"[错误] 0x{frame.err_code:02X} {frame.err_name}")

    def _on_stats(self, stats: dict) -> None:
        self._seq_label.setText(f"SEQ: {stats['last_seq']}" if stats["last_seq"] is not None else "SEQ: -")
        self._drop_label.setText(f"丢帧: {stats['dropped']}")
        self._rate_label.setText(f"{stats['rate_hz']:.1f} Hz")

    # ── 定时器 ──
    def _refresh_chart(self) -> None:
        self._plot.refresh()

    def _update_stats(self) -> None:
        self._on_stats(self._source.stats)

    def _log_health(self) -> None:
        """HEALTH 行：Logging_Standard §6 要求的五个字段齐全。"""
        try:
            import psutil
            proc = psutil.Process()
            rss_mb = proc.memory_info().rss / (1024 * 1024)
            cpu_pct = psutil.cpu_percent(interval=None)
            threads = proc.num_threads()
        except Exception:
            rss_mb, cpu_pct, threads = 0.0, 0.0, 0
        uptime = int(time.monotonic() - self._t_start)
        stats = self._source.stats
        logger.info(
            "HEALTH | uptime=%ds | rss=%.1fMB (Δ%+.1f) | cpu=%.1f%% | thr=%d | "
            "q=%d/%d | rate=%.1f/s | dropped=%d | err=%d",
            uptime, rss_mb, rss_mb - self._rss_prev, cpu_pct, threads,
            stats["samples"], stats["frames"], stats["rate_hz"],
            stats["dropped"], stats["errors"],
        )
        self._rss_prev = rss_mb

    # ── CSV ──
    def _toggle_csv(self) -> None:
        if self._csv is not None:
            self._csv.close()
            self._csv = None
            self._save_btn.setText("保存 CSV")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存采集数据", "tmag_data.csv", "CSV Files (*.csv)"
        )
        if not path:
            return
        self._csv = CsvWriter(path)
        self._csv.open()
        self._save_btn.setText("停止保存")
        logger.info("开始保存采集数据: %s", path)

    def _clear(self) -> None:
        self._plot.clear()

    # ── 主题 / 设置 ──
    def _apply_theme(self) -> None:
        app = self._application()
        if app is not None:
            app.setStyleSheet(ColorScheme.get_stylesheet())
        self._plot.apply_theme()

    def _on_color_changed(self, role: str) -> None:
        self._apply_theme()
        self._save_settings()

    def _restore_settings(self) -> None:
        for role, value in self._settings.get("colors", {}).items():
            try:
                ColorScheme.set_color(role, value)
            except (KeyError, ValueError):
                continue
        self._apply_theme()
        port = self._settings.get("acquisition", {}).get("port", "")
        if port:
            self._port_combo.setCurrentText(port)

    def _save_settings(self) -> None:
        data = self._settings
        data["colors"] = ColorScheme.snapshot()
        data["acquisition"]["port"] = self._port_combo.currentText()
        data["acquisition"]["baud"] = int(self._baud_combo.currentText())
        save_settings(data)

    # ── 全屏 ──
    def _toggle_fullscreen(self) -> None:
        self.showFullScreen()

    def _exit_fullscreen(self) -> None:
        self.showNormal()

    def closeEvent(self, event) -> None:
        self._source.close()
        if self._csv is not None:
            self._csv.close()
        self._save_settings()
        event.accept()
```

> 上面 `body = QSplitter(Qt_Horizontal := 1)` 是笔误，**必须**改为：
> ```python
> from PyQt5.QtCore import Qt
> body = QSplitter(Qt.Horizontal)
> ```

- [ ] **Step 3: 修改 `host/run.py`，应用 QSS 并接入日志**

```python
def main() -> int:
    from tmag_viewer.log_setup import setup_logging

    log_path = setup_logging("tmag_viewer", str(Path(__file__).resolve().parent / "logs"))
    logging.getLogger(__name__).info("Logging initialized: %s", log_path)

    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from tmag_viewer.color_scheme import ColorScheme

    app.setStyleSheet(ColorScheme.get_stylesheet())

    from tmag_viewer.main_window import MainWindow

    win = MainWindow()
    win.show()
    return app.exec_()
```

- [ ] **Step 4: 冒烟验证（offscreen）**

在 `host/` 下创建 `host/_smoke_ui.py`：

```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication
app = QApplication([])
from tmag_viewer.main_window import MainWindow
w = MainWindow()
print("ui smoke OK, panels:", w._plot is not None, w._color_panel is not None)
```

Run: `cd F:\youko_repo\Tmag3001_for_STM32F4_\host; C:\ProgramData\Anaconda3\python.exe _smoke_ui.py`
Expected: 打印 `ui smoke OK, panels: True True`。

- [ ] **Step 5: 提交**

```
feat(host): 颜色面板与主窗口

- ColorPanel：170px 侧栏，3 区域 × 每行色块/角色名/hex 输入/取色器 + 重置
- MainWindow：控制面板 + XYZ/温度图表 + 颜色面板 + 日志面板 + 状态栏
- 严格遵循 Logging_Standard：模块 logger、HEALTH 行、%s 惰性格式化、
  串口行带 [transport=serial][addr=...] 标签
- 灵敏度只来自状态帧，未收到状态帧前不显示数值曲线
```

---

### Task B9: 端到端联调与验收

**Files:**
- Modify: `host/tmag_viewer/main_window.py`（按实测修正）
- Create: `docs/superpowers/plans/2026-11-07-host-viewer-acceptance.md`（验收记录）

**Interfaces:**
- Consumes: Task B1–B8、固件计划的 Task 7/8
- Produces: 验收记录，对应 spec 的 A4/A5/A6/A7/A8

- [ ] **Step 1: 连机实测（传感器已接）**

1. 固件烧录：`tools\flash.ps1 Release`
2. 启动应用：`cd host; C:\ProgramData\Anaconda3\python.exe run.py`
3. 串口选 **COM9**，波特率 115200，点"连接"。

Expected:
- 状态栏显示"传感器: 就绪"、量程 `±40mT (885 LSB/mT)`、帧率接近实测速率
- 图表出现 X/Y/Z 三条曲线与温度曲线
- 丢帧计数为 0（或极小）
- 日志面板能看到 `[transport=serial][addr=COM9@115200]` 开头的信息行

- [ ] **Step 2: 验收 A5（数值正确性）**

用 `tools/hosttest/test_capture.py` 抓一帧原始值，与应用显示值对照：

```powershell
C:\ProgramData\Anaconda3\python.exe tools\hosttest\test_capture.py --port COM9 --seconds 3
```

手算校验：`mT = raw / 885`。**若应用显示值与 `raw/885` 不符 → 说明灵敏度来源有问题（禁止硬编码，必须来自状态帧）**。

- [ ] **Step 3: 验收 A6（日志规范）**

检查 `host/logs/tmag_viewer_*.log`：
- 存在 `HEALTH | uptime=... | rss=...MB | cpu=...% | thr=... | q=.../... | rate=...` 行
- 存在 `[transport=serial][addr=COM9@115200]` 行
- 行首时间戳与级别齐全
- 30 s 内的日志行数合理（**不是**每采样一行）

- [ ] **Step 4: 验收 A7（传感器未接）**

断开传感器或断开 I2C，重跑：
- 应用显示"传感器: 未就绪"
- 日志出现 `I2C_NACK`
- **应用不崩溃**，图表为空但界面可交互

- [ ] **Step 5: 验收 A8（CSV 原子写）**

点"保存 CSV"→ 采几秒→点"停止保存"：
- 目标文件存在且可被 `csv.reader` 读
- 目录下无残留 `.tmag-*.tmp`
- 在保存过程中（未点停止）目标文件**不出现**（只有 tmp）

- [ ] **Step 6: 写验收记录**

`docs/superpowers/plans/2026-11-07-host-viewer-acceptance.md`：

```markdown
# PC 端验收记录（2026-11-07）

| 验收项 | 结果 | 证据 |
|---|---|---|
| A4 数据帧连续、SEQ 无跳变 |  | 抓包输出 |
| A5 曲线与量程正确 |  | raw/885 手算对照 |
| A6 日志符合 Logging_Standard |  | 日志文件片段 |
| A7 传感器未接不崩溃 |  | 截图/日志 |
| A8 CSV 原子写 |  | 目录列表 |
```

- [ ] **Step 7: 提交**

```
test(host): 端到端联调与验收

验收记录见 docs/superpowers/plans/2026-11-07-host-viewer-acceptance.md。
```

---

### Task B10: 打包与最终文档

**Files:**
- Create: `host/tmag_viewer.spec`（PyInstaller）
- Modify: `README.md`（补 PC 端章节）
- Modify: `host/requirements.txt`

**Interfaces:**
- Consumes: Task B1–B9
- Produces: 可分发的 `TMAGViewer.exe`；README 含 PC 端使用说明

- [ ] **Step 1: 写 `host/tmag_viewer.spec`**

```python
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（参考 F:\\Phd\\20260409_TMAG_3axis_visaulization\\TMAGViewer.spec）。"""

block_cipher = None

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['serial.tools.list_ports', 'serial.tools.list_ports_windows'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='TMAGViewer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
```

> PyInstaller **未安装**，本轮**不执行打包**，只提交 spec 文件作为后续入口。若要打包需先 `pip install pyinstaller`（属于新增依赖，超出本轮范围）。

- [ ] **Step 2: 在 `README.md` 追加 PC 端章节**

```markdown
## PC 端可视化

```bash
cd host
C:\ProgramData\Anaconda3\python.exe -m pytest          # 单元测试
C:\ProgramData\Anaconda3\python.exe run.py             # 启动应用
```

- 串口选 **COM9**，波特率 **115200**（ST-Link 虚拟串口）
- 量程与灵敏度由固件状态帧自动下发，**应用不硬编码**
- 日志在 `host/logs/tmag_viewer_*.log`（含 `[transport=serial][addr=...]` 与 `HEALTH` 行）
- 采集数据用"保存 CSV"导出（原子写）

**注意**：Python 脚本必须在仓库目录内运行。`%TEMP%` 目录下存在残留模块
（`inspect.py` 等），会污染 stdlib 导入并触发
`ImportError: cannot import name 'currentframe'`。
```

- [ ] **Step 3: 提交**

```
docs(host): PyInstaller 配置与 PC 端使用说明

spec 文件沿用旧 TMAGViewer.spec 的结构；本轮不执行打包
（PyInstaller 未安装，超出本轮依赖范围）。
```

---

## Self-Review

**Spec 覆盖检查（spec §7 + §9 的 PC 端部分）**

| Spec 条款 | 对应任务 |
|---|---|
| §7.1 模块划分（8 个模块） | B2 `protocol`、B3 `log_setup`、B4 `color_scheme`、B5 `settings_manager`、B6 `serial_source`、B7 `plot_widgets`、B8 `color_panel`+`main_window`、B6 `csv_writer` |
| §7.2 颜色角色（11 个，3 类） | B4 |
| §7.3 Logging_Standard 落地清单（9 条） | B3（setup_logging）、B6（transport 标签）、B8（HEALTH 行、%s 惰性）、B6（CSV 原子写） |
| §7.4 UI 布局（控制栏/图表/右侧/底部/状态栏/F10-Esc） | B8 |
| §9 A4 数据帧连续 | B9 Step 1 |
| §9 A5 曲线与量程正确 | B9 Step 2 |
| §9 A6 日志规范 | B9 Step 3 |
| §9 A7 未接传感器不崩 | B9 Step 4 |
| §9 A8 CSV 原子写 | B9 Step 5 |
| §9 A9 .gitignore 生效 | 固件计划 Task 1（含 `host/build`、`host/dist`、`host/logs`、`__pycache__`） |

**无遗漏**：A1/A2/A3/A10 属固件范围，在固件计划中验收。

**占位符扫描**：本计划无 TBD/TODO；代码块给出完整内容；Task B8 的 `QSplitter(Qt_Horizontal := 1)` 笔误已在同一步骤内显式标注修正方式。

**类型一致性核对**：
- `protocol.encode_data(seq, x_raw, y_raw, z_raw, temp_raw)` — B2 定义，B2 测试调用 ✓
- `Frame` 字段 `x_raw/y_raw/z_raw/temp_raw`、`sensitivity`、`range_name`、`to_mt()` — B2 定义，B8 使用 ✓
- `ColorScheme.set_color/adjust/hex_to_rgba/get_stylesheet/snapshot/ROLES` — B4 定义，B5/B7/B8 使用 ✓
- `settings_manager.load_settings/save_settings/DEFAULTS` — B5 定义，B8 使用 ✓
- `CsvWriter.open/write/close` — B6 定义，B6 测试与 B8 使用 ✓
- `SerialSource` 信号名 `sample_received/status_received/error_received/stats_updated` — B6 定义，B8 连接 ✓
- `protocol.ERR_NONE/ERR_I2C_NACK`、`FLAG_SENSOR_READY/FLAG_CFG_OK/FLAG_INT_PATH_OK` — B2 定义，B8 使用 ✓
- golden vector 五组在 B2 测试中硬编码，与固件 C 实现同一组字节 ✓

> 采样率统一补充：逻辑整数 0..255 直接编码；256..2550 仅精确 10 Hz 倍数可编码，其他值拒绝。0 表示未知/未配置。编码器从逻辑 Hz 重算并清/置 bit7，保留 bit6，由 range_code 重算 bits0-1。字段为名义配置 Hz，PC 以数据帧数/经过时间独立测实际 Hz。固件毫秒调度器更窄：`0 < rate <= 1000` 且 `1000 % rate == 0`，编译期拒绝其他配置；100/200/500/1000 Hz 可表示但尚未实测。SEQ 跨数据/状态/错误全部帧全局递增，丢帧检查覆盖全部有效帧。

> Device_Status 更正（datasheet §7.1.29，PDF第57页）：bit4 INT_RB、bit2 INT_ER、bit1 OTP_CRC_ER、bit0 THR_Cross，没有 overflow 位。0x08 OVERFLOW 仅保留兼容编号，无已证实溢出条件不得发出；THR_Cross/INT_RB 不得当溢出。INT_ER/OTP_CRC_ER 映射 ERR_SENSOR_DIAG。Task5/6 必须读取并上报实际 Device_Status，不得始终发送初始化0；需驱动/应用测试验证。
