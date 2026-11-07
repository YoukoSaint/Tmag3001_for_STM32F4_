# TMAG3001 / STM32F411 采集与显示

固件通过I2C触发TMAG3001转换，默认纯轮询，经USART1输出二进制帧；Python桌面端显示XYZ/温度并保存CSV。**当前固定使用100 Hz，用户已要求停止高频测试。** 抓包工具修复重复串口配置后，35.047秒实测3501 DATA、实际99.894 Hz、零SEQ缺口/跳过字节/错误；真实上位机曲线与CSV已通过联调，现交由用户测试。代码与历史证据见[执行状态](docs/superpowers/plans/2026-11-07-execution-status.md)和[扫频记录](docs/superpowers/plans/2026-11-07-sample-rate-sweep-results.md)。

按用户授权，当前默认 `APP_USE_INT=0` 纯轮询转换完成状态，每1 ms检查、5 ms超时，关闭传感器 INT 输出；设置 `APP_USE_INT=1` 可选择原 INT 模式。PB5 的板级输入/IRQ配置保留，轮询模式忽略边沿、INT_PATH_OK保持0。初次10秒实测989组DATA、98.447 Hz、0诊断错误，仍有11个SEQ缺口和63个解析跳过字节。

## 工程与环境

以下 PowerShell 命令均从工程根目录运行：

```powershell
Set-Location 'F:\youko_repo\Tmag3001_for_STM32F4_'
$python = 'C:\ProgramData\Anaconda3\python.exe'
```

已使用的环境为 CMake 3.28.1、Ninja、Arm GNU GCC 14.3.1、STM32CubeCLT 1.21.0；宿主 C 测试另需 MinGW GCC。Python 3.9 环境已具备 PyQt5、pyqtgraph、pyserial、numpy、psutil、pytest，依赖清单在 `host/requirements.txt`。本次没有安装或更新依赖。

HAL/CMSIS 从外部 STM32CubeF4 V1.28.3 使用，不入库、不修改。默认查找 `%USERPROFILE%/STM32Cube/Repository/STM32Cube_FW_F4_V1.28.3`；其他位置可用环境变量 `STM32CUBE_F4_PATH` 或 CMake cache `-DSTM32CUBE_F4_PATH=...` 指定包根目录。cache 显式路径优先于环境变量；显式路径无效会报错，不能靠默认路径掩盖。已有 cache 时应同步更新该值。

```powershell
# 仅在使用其他 SDK 路径时设置；填入实际存在的包目录
$env:STM32CUBE_F4_PATH = 'D:\STM32Cube\Repository\STM32Cube_FW_F4_V1.28.3'
cmake --preset Release -DSTM32CUBE_F4_PATH="$env:STM32CUBE_F4_PATH"
```

工程使用根目录 `STM32F411XX_FLASH.ld`（512 KB FLASH / 128 KB RAM）及 F411 启动文件。`App/` 为协议与采集调度，`Drivers/Tmag3001/` 为当前驱动，`Core/` 为板级初始化；ST7789 遗产代码保留但不参与构建。无需点击 CubeMX Generate Code；不要用旧 F407 驱动替换本工程驱动。

## 构建、探测与烧录

```powershell
.\tools\build.ps1 -Preset Release
.\tools\probe.ps1                 # 仅枚举接口，不复位
.\tools\probe.ps1 -ReadCpuid      # SWD HOTPLUG 读取 CPUID，不复位
.\tools\flash.ps1 -Preset Release # 写入、-v 校验、-rst 复位
```

构建输出为 `build/Release/TMA3001_.elf`。烧录脚本依据 Ninja 构建图和编译器头文件依赖检查产物新鲜度，包含选定的 SDK；缺少依赖记录或需要重建时拒绝烧录。Programmer CLI 默认来自 CubeCLT 1.21.0，可通过 `STM32_PROGRAMMER_CLI` 或 `-ProgrammerPath` 指定。单独复位必须显式运行 `.\tools\probe.ps1 -Reset`。

## 接线与首次采集

| 信号 | 接线 |
|---|---|
| 电源 | 3.3 V、共地 |
| I2C1 | SCL → PB6，SDA → PB7 |
| 转换完成（可选 INT 模式） | INT → PB5；外接 10 kΩ 上拉到 3.3 V，板端启用内部上拉；默认轮询不依赖此边沿 |
| USART1 | PA9 TX → 转接器 RX，PA10 RX → 转接器 TX；共地 |
| 串口 | 当前 COM9，115200 / 8N1 |

固件默认 ±40 mT、885 LSB/mT、名义 100 Hz、I2C 100 kHz。传感器地址扫描 0x34..0x37；本机已在 0x34 响应并通过配置回读。USART1 需要实际接到串口转接器，不能仅凭 ST-Link 枚举认定 VCP 已接线。

```powershell
& $python tools/hosttest/test_capture.py --port COM9 --baud 115200 --seconds 10 --json-out build/hardware/first-status.json
# 取得有效状态后，健康链路检查还必须要求 DATA
& $python tools/hosttest/test_capture.py --port COM9 --baud 115200 --seconds 10 --require-data --json-out build/hardware/healthy.json
```

抓包只读串口。默认成功条件包含有效状态，**不等于健康采集成功**；还须有连续 DATA，并确认 SENSOR_READY、CFG_OK、正灵敏度，以及当前 `CONV_STATUS & 0x02 == 0`、`DEVICE_STATUS & 0x06 == 0`。状态中的 Hz 是配置值；实际 DATA Hz 应由 DATA 数量与经过时间单独计算。

可选取证参数为 `--raw-out build/hardware/new-capture.bin`（保留读到的原始字节、拒绝覆盖已有文件）和 `--flush-input`（打开串口后显式清输入缓冲，默认不清）。清缓冲会丢弃此前积压数据，应记录是否使用；JSON 记录字节数、帧结束偏移和 `raw_complete`，失败时原始文件可能不完整。已保存健康轮询原始字节证据。`--read-size` 可做单变量读取实验，默认4096；实测1字节读取显著恶化，不推荐用于当前ST-Link VCP。

原 INT 模式持续报告 DeviceStatus=0x14、无DATA；关闭传感器INT输出后，轮询模式已报告 DeviceStatus=0x10、诊断位清零并产生DATA。bit4 INT_RB是回读状态，bit2 INT_ER才是诊断故障。每次App_Init最多用W1C 0x04清一次历史INT_ER，不清OTP或循环掩盖错误。扫频期间另观察到SDA低、SCL高、I2C BUSY；现已加入前台有界总线恢复，详见执行状态。不能据此判定模块损坏。

## 桌面端使用（由用户主动启动）

本机可直接双击根目录 `启动上位机.bat`，使用现有Anaconda Python打开界面；选择COM9、115200后连接。启动失败会保留控制台错误提示。移动到其他电脑时，可修改BAT中的VIEWER_PYTHON路径。

```powershell
& $python host/run.py
```

选择端口及 115200，点击“连接”。有效状态到达后才按该状态的灵敏度换算磁场；界面分别显示配置 Hz 与实际 Hz。可切换颜色面板、运行日志和 Kalman 显示平滑；平滑只影响 XYZ 显示，CSV 保存未滤波工程值。点击“保存 CSV”选择目标并开始记录，再次点击结束；关闭窗口会执行收尾。故障时应先看状态/日志，不用空白曲线推断磁场为零。

日志位于 `host/logs/`，配置为 `host/settings.json`。这些文件、CSV、build、HAL/CMSIS和宿主打包产物均已忽略。已完成35秒实机联调：3491 DATA、3469行CSV逐行核对、四条真实曲线、自然30秒HEALTH及退出清理均通过；SEQ缺口仍在，物理拔线中断和EXE分发未验证。详见[上位机验收](docs/superpowers/plans/2026-11-07-host-viewer-acceptance.md)。

## 离线验证

以下命令不连接真实串口；C 检查会调用宿主编译器，Qt 测试使用离屏平台：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
& $python -m pytest host/tests --basetemp=build/host-pytest
& $python -m pytest tools/hosttest/test_capture_unit.py --basetemp=build/capture-pytest
.\tools\hosttest\run_tests.ps1
.\tools\hosttest\run_driver_tests.ps1
.\tools\hosttest\run_app_tests.ps1
.\tools\hosttest\test_flash_guard.ps1
.\tools\hosttest\test_sweep_plan.ps1
```

最近报告：协议147、驱动2068；总线恢复636、应用679项轮询/2253项INT检查，以及默认/0/1模式速率矩阵通过；宿主/抓包/验收合并319项通过（13.45秒）；扫频安全检查93项通过。离线通过不能替代下表硬件验收。

| 验收 ID | 当前状态 |
|---|---|
| A1 构建 | PASS，Release 无警告 |
| A2 烧录 | PASS，真实写入、校验及复位成功 |
| A3 状态 | PASS，触发标志修正后取得有效、字段自洽的状态 |
| A4 健康连续 DATA | 已有健康XYZ/温度；仍有SEQ缺口，零丢帧门槛未通过 |
| A5 实时曲线 | PASS，35秒实机四条曲线，各保留2000点 |
| A6 日志 | PASS，真实串口生命周期、自然30秒HEALTH及退出清理 |
| A7 故障路径 | 真实NACK与INT诊断已观察；PC离线故障回放通过，实机故障正确显示并阻止健康验收通过 |
| A8 原子 CSV | 实机3469行逐行值核对与正常收尾通过；物理拔线中断未实测 |
| A9 忽略规则 | PASS，生成物与外部 SDK 不入库 |
| A10 采样率扫频 | 四档均实测；100/200约98/196 Hz，500约378 Hz；1000发生总线故障，不认定稳定上限 |

扫频先执行 `.\tools\sweep.ps1 -DryRun` 检查计划；实际执行必须提供健康初始抓包。具体门槛、命令与恢复行为见[扫频记录](docs/superpowers/plans/2026-11-07-sample-rate-sweep-results.md)。

## 打包模板（尚未构建验证）

`host/tmag_viewer.spec` 是窗口模式、目录分发的 PyInstaller 模板，入口为 `host/run.py`，模块路径相对 spec 定位，使用 Qt/pyqtgraph 标准 hooks 和 Windows 串口隐藏导入。写法参考 [PyInstaller 官方 spec 文档](https://pyinstaller.org/en/stable/spec-files.html)。本次没有安装/执行 PyInstaller，没有可分发或已验证的 EXE。

后续在具有合适 PyInstaller 的独立环境中，可从工程根目录手动构建：

```powershell
& $python -m PyInstaller --workpath host/build --distpath host/dist host/tmag_viewer.spec
```

预期产物为 `host/dist/TMAGViewer/TMAGViewer.exe` 及同目录依赖。交付前仍需实际验证启动、Qt 插件、串口、日志/设置可写性与 CSV；不能仅凭 spec 语法检查发布。

协议唯一契约见 [TMAG3001_Protocol.md](docs/protocol/TMAG3001_Protocol.md)。历史设计与计划位于 `docs/superpowers/`，具体实施与验收事实以执行状态和本 README 为准。
