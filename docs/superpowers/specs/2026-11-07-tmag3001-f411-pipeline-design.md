# TMAG3001 × STM32F411 采集链路重构设计

- 日期：2026-11-07
- 状态：待用户评审
- 工程根目录：`F:\youko_repo\Tmag3001_for_STM32F4_`
- 目标仓库：https://github.com/YoukoSaint/Tmag3001_for_STM32F4_

---

## 1. 目标

把一个"只存在于本地未提交工作区"的 F411 固件项目，变成**仓库内可构建、可烧录、可复现**的工程，并建立一条**固件 → PC 端**的可靠数据链路：

1. 固件只做一件事：采集 TMAG3001 磁场/温度，按二进制协议发出去，并维护一组**规范状态码**。
2. 所有日志、诊断、可视化都在 PC 端，按 `Logging_Standard_for_Agent` 的规范实现。
3. PC 端 UI 按 `UI_palette` 的架构思想重构（颜色角色单一真相源 + 主题面板 + 设置持久化）。

**明确不做**：板上显示屏（ST7789）任何工作。板子是纯数据采集设备。

---

## 2. 现状盘点（均已实测核实）

### 2.1 仓库现状

| 项 | 事实 |
|---|---|
| GitHub master | 仅 5 个文件：`main.c` / `main.h` / `tmag3001_driver.{c,h}` / `TMA3001_.ioc` |
| 提交历史 | 只有 1 次提交 `767a541` "Realize the model acquisition of Tmag3001 magnetometer." |
| 缺失 | HAL、CMSIS、启动文件、链接脚本、CMake —— **当前 master 连编译都做不了** |
| `.ioc` | `Mcu.CPN=STM32F411CEU6`，`UFQFPN48`，但外设只有 DMA/I2C1/NVIC/RCC/SYS/TIM2/USART1，**无 SPI、无 EXTI** |

### 2.2 本地遗产（同一 remote、同一 commit，工作区未提交）

`F:\Phd\GIT_YOUKOSAINT\TMA3001_`：272 文件 / 31.9 MB，其中约 270 个未跟踪或已修改：

- 完整 HAL + CMSIS（ST 厂商代码）
- `STM32F411XX_FLASH.ld`、`startup_stm32f411xe.s`
- CubeMX 生成的 CMake 工程（`CMakeLists.txt` / `CMakePresets.json` / `cmake/`）
- `Drivers/ST7789/`（屏幕驱动 + 三套点阵字体，`fonts.c` 1.37 MB）+ `st7789-bugfix-postmortem.md`（5 个 DMA/CS bug 复盘）
- `Drivers/Tmag3001/`（传感器驱动）

`F:\Phd\20260325_Tmag3001_test`（F407 CubeIDE 工程，324 文件）与其副本 `F:\Phd\20260330_Tmag3001\20260325_Tmag3001_test`：**无 UI、无 SPI、协议编码器缺失**，本项目不采用。

### 2.3 PC 端遗产

`F:\Phd\20260409_TMAG_3axis_visaulization\`：

- `tmag_viewer.py`（17.7 KB）：可用的 PyQt5 应用 —— 串口采集、CRC 校验、Kalman 滤波、三子图曲线、丢帧统计、CSV 保存
- `TMAG3001_Protocol.md`（7.6 KB）：协议 v1.1 规范（10 字节帧 + CRC-8 + 错误帧）
- `TMAGViewer.spec` / `build.py` / `setup_build_env.py` / `dist/TMAGViewer.exe`（PyInstaller 打包）

### 2.4 两个必须纠正的既有缺陷

**缺陷 A —— F407 驱动的寄存器映射是错的。**

| | F407 驱动（2026-03-25，引用 SBAS993） | F411 驱动（2026-04-09，引用 ZHCSR44C / SLYS053） | datasheet 真值（ZHCSR44C，已逐页核对） |
|---|---|---|---|
| 0x00 | X_Result | Device_Config_1 | Device_Config_1 |
| 配置区 | 0x05–0x0D | 0x00–0x0C | 0x00–0x0C |
| 结果区 | 0x00–0x03 | 0x10–0x1B | 0x10–0x1B |
| 量程 | 40/80/120/160 mT | 40/80 mT | A1: 40/80 mT；A2: 120/240 mT |
| 厂商 ID | 0x35 | 0x49(LSB) / 0x54(MSB) | 0x49 / 0x54 ✓ |

结论：**F411 驱动是对的**，F407 那份整体作废，禁止混用或移植。

**缺陷 B —— 现有 PC 端把灵敏度硬编码成 446 LSB/mT（±80 mT），而 F411 固件配置的是 ±40 mT（885 LSB/mT）。** 照现状跑，PC 端显示的磁场值会偏小 885/446 ≈ 1.98 倍。→ 必须由固件在状态帧里下发实际量程与灵敏度。

### 2.5 INT 引脚：原来没接

- F407 工程把 `INT1` 标在 **PA8**，但配置为 `GPIO_MODE_OUTPUT_PP`（推挽**输出**），无 EXTI、无中断处理 —— 是占位/误配，不是真正的中断输入。
- F411 工程（本地遗产）**完全没有 EXTI 外设**。
- **用户现状（2026-11-07 新增事实）：传感器 INT 已接至 F411 的 PB5。**

### 2.6 工具链（已实测可用）

| 工具 | 位置 / 版本 |
|---|---|
| CMake | `C:\ST\STM32CubeCLT_1.21.0\CMake\bin\cmake.exe` → 3.28.1 |
| Ninja | `C:\ST\STM32CubeCLT_1.21.0\Ninja\bin\ninja.exe` |
| arm-none-eabi-gcc | `C:\ST\STM32CubeCLT_1.21.0\GNU-tools-for-STM32\bin\` → **14.3.1** |
| 烧录 | `C:\ST\STM32CubeCLT_1.21.0\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe` → 2.22.0 |
| 调试 | `C:\ST\STM32CubeCLT_1.21.0\STLink-gdb-server\bin\ST-LINK_gdbserver.exe` |
| OpenOCD（备选） | `C:\OpenOCD-20250710-0.12.0\bin\openocd.exe`（未入 PATH） |
| F4 固件包 | `C:\Users\Youko\STM32Cube\Repository\STM32Cube_FW_F4_V1.28.3`（与 `.ioc` 声明一致） |
| Python | `C:\ProgramData\Anaconda3\python.exe` → 3.9.12；已装 PyQt5 5.15.11 / pyqtgraph 0.13.7 / pyserial 3.5 / numpy 2.0.2 |

**ST-Link 实测**：`STM32_Programmer_CLI -l` 识别到 ST-Link V2（SN `004800454A00001156313848`，FW V2J46M33）；SWD 连接成功，目标识别为 **STM32F411xC/E**（Device ID 0x431，512 KB Flash，Cortex-M4，3.24 V）；**ST-Link 虚拟串口 = COM9**。

> 注：遗留 `CLAUDE.md` 写"串口在 COM3"是错的，COM3/COM7 是 Microsoft 虚拟口。

---

## 3. 范围

### 3.1 本轮包含

1. 工程归集：把本地遗产的关键代码并入仓库，`.gitignore` 排除 ST 厂商代码与构建产物；CMake 改为从本机 CubeF4 包解析 HAL/CMSIS。
2. 构建与烧录脚本化：`tools/build.ps1`、`tools/flash.ps1`、`tools/probe.ps1`。
3. 固件重构：`App/` 分层 + PB5/EXTI5 传感器中断 + 协议编码器 + 状态码体系。
4. PC 端重构：`host/` 模块化应用，按 UI_palette + Logging_Standard 实现。
5. 文档：README（工具链与速查）、协议文档 v1.2、移植/踩坑说明。

### 3.2 本轮不包含

- ST7789 屏幕：驱动与字体代码**保留在仓库但不参与构建**（不删除用户已有工作），README 标注"屏幕支持暂缓"。
- CubeMX 重新生成代码（见 §5.4 的工程管理约定）。
- LVGL / FreeRTOS。
- PyInstaller 打包（`TMAGViewer.spec` 已存在，后续可复用）。

---

## 4. 目标架构

```
┌──────────────────────────── STM32F411CEU6 ────────────────────────────┐
│  TMAG3001 (I2C1, PB6/PB7 @100kHz)                                       │
│      │  INT (开漏输出, 低有效)                                            │
│      ▼  PB5 / EXTI5 下降沿                                                │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────────────────────┐  │
│  │ App/app.c    │   │ Drivers/     │   │ App/Proto/tmag_proto.c   │  │
│  │ 采样状态机    │──▶│ Tmag3001/    │──▶│ 帧编码 + CRC-8           │  │
│  │ EXTI/TIM 兜底 │   │ 寄存器读写    │   │ 数据帧/状态帧/错误帧       │  │
│  └──────────────┘   └──────────────┘   └───────────┬───────────────┘  │
└─────────────────────────────────────────────────────┼──────────────────┘
                                                      │ USART1 PA9/PA10 @115200
                                                      │ (ST-Link VCP → COM9)
┌─────────────────────────────────────────────────────┼──────────────────┐
│  PC 端 (Anaconda Python 3.9)                          ▼                  │
│  host/tmag_viewer/                                                        │
│   serial_source.py ──(QThread + pyqtSignal)──▶ plot_widgets.py         │
│        │ (protocol.py 解析 12 字节帧)                    │              │
│        ▼                                              ▼              │
│   main_window.py (UI_palette 架构：ColorScheme/主题面板/设置持久化)      │
│   log_setup.py (Logging_Standard：模块 logger / HEALTH / FILE_IO)       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 5. 固件设计

### 5.1 目录结构（新增/调整）

```
Tmag3001_for_STM32F4_/
├── App/                              # 新增：应用层（CubeMX 不碰）
│   ├── Inc/
│   │   ├── app.h                     # 采样状态机 + 公共接口
│   │   ├── app_config.h              # 量程/采样率/协议版本（单一真相源）
│   │   └── tmag_proto.h              # 帧编码 API + 状态码枚举
│   └── Src/
│       ├── app.c                     # 初始化流程 + 主循环 + EXTI 回调
│       └── tmag_proto.c              # 帧编码 + CRC-8
├── Core/
│   ├── Inc/{main.h, stm32f4xx_hal_conf.h, stm32f4xx_it.h}
│   └── Src/{main.c, stm32f4xx_it.c, stm32f4xx_hal_msp.c,
│             system_stm32f4xx.c, syscalls.c, sysmem.c}
├── Drivers/
│   ├── Tmag3001/                     # 传感器驱动（沿用 F411 版 + 新增 INT 配置）
│   ├── ST7789/                       # 保留，不参与构建
│   ├── STM32F4xx_HAL_Driver/         # ← gitignored
│   └── CMSIS/                        # ← gitignored
├── cmake/
│   ├── gcc-arm-none-eabi.cmake       # 沿用
│   ├── starm-clang.cmake             # 沿用（备选工具链）
│   └── firmware_sources.cmake        # 新增：HAL/CMSIS 定位 + 源文件清单
├── tools/{build.ps1, flash.ps1, probe.ps1}   # 新增
├── host/                             # 新增：PC 端
├── docs/
│   ├── protocol/TMAG3001_Protocol.md # v1.2
│   └── superpowers/specs/            # 本文档
├── CMakeLists.txt / CMakePresets.json
├── startup_stm32f411xe.s / STM32F411XX_FLASH.ld / TMA3001_.ioc
└── .gitignore / README.md
```

### 5.2 传感器配置（依据 datasheet ZHCSR44C 逐位核对）

| 寄存器 | 位 | 值 | 理由 |
|---|---|---|---|
| `Device_Config_1` (0x00) | `CRC_EN[7]` | 0 | MCU 侧自己算 CRC，禁用器件 I2C CRC 以简化读取 |
| | `Conv_AVG[4:2]` | 0 (1x) | 单次转换最快；噪声由 MCU 侧滤波兜底 |
| | `I2C_RD[1:0]` | 0 | 标准 3 字节读取命令（先写寄存器指针，再读） |
| `Device_Config_2` (0x01) | `Trigger_Mode[2]` | 0 | **转换由 I2C 命令位触发**（见 §5.3 理由） |
| | `Operating_Mode[1:0]` | 0 | 待机/触发模式 —— 转换不连续发生，不产生 overrun |
| `Sensor_Config_1` (0x02) | `MAG_CH_EN[7:4]` | 7 | X/Y/Z 三通道 |
| `Sensor_Config_2` (0x03) | `T_Rate[7]` | 1 | 温度按 Conv_AVG 滤波 |
| | `INTB_POL[6]` | 0 | **INT 默认高、中断期间低有效** → MCU 配下降沿 |
| | `X_Y_Range[1]` / `Z_Range[0]` | 0 | ±40 mT（TMAG3001A1） |
| `INT_Config_1` (0x08) | `Result_INT[7]` | 1 | **转换完成即产生中断**（data-ready） |
| | `INT_State[5]` | 0 | **锁存**（而非 5 µs 脉冲）—— 5 µs 太短易丢；锁存由"控制器寻址器件"清除，我们的读事务正好清除 |
| | `INT_Mode[4:2]` | 1 | 经 INT 引脚输出中断 |
| | `INT_POL_EN[1]` | 1 | 使能 `INTB_POL` |
| | `MASK_INT[0]` | 0 | INT 引脚可用 |

**灵敏度表**（固件与状态帧均使用）：

| 变体 | 量程 | LSB/mT |
|---|---|---|
| TMAG3001A1 | ±40 mT | 885 |
| TMAG3001A1 | ±80 mT | 446 |
| TMAG3001A2 | ±120 mT | 273 |
| TMAG3001A2 | ±240 mT | 137 |

### 5.3 采样模型

**为什么用"I2C 触发 + INT 报完成"，而不是"MCU 驱动 INT 触发"：**
`Trigger_Mode=1` 可由 INT 引脚触发转换，但那样 INT 引脚就是 MCU 的**输出**，无法同时作为传感器的**开漏中断输出**（同一根线不能既驱动又回读）。而 `Trigger_Mode=0` 时 INT 只做输出，职责单一、无冲突。因此：

```
主循环：
  if (!data_ready && 距上次触发 >= 10 ms):
        写 Device_Config_1（回写当前值，A/T=1）→ 触发转换
        armed = true; armed_at = now

EXTI5_IRQHandler / HAL_GPIO_EXTI_Callback(PB5):
        下降沿 → data_ready = true        ← 中断里只置标志，不做 I2C

主循环（data_ready == true）:
        读 X/Y/Z/T + Conv_Status（0x10-0x18，9 字节一次事务）
        编码数据帧 → UART DMA 发送
        若 5 ms 内 EXTI 未触发 → 读 Conv_Status 兜底；仍无 Result_Status
              → 发错误帧 ERR_NO_CONV，并在状态帧标记 INT 路径失效
```

- **采样率 100 Hz**（10 ms/帧），与协议文档 v1.1 和既有 PC 端预期一致。
- 100 Hz × 12 B = 1200 B/s，占 115200 bps 的 **10.4%**，带宽充裕。
- **INT 上拉**：INT 是开漏输出，datasheet 明确"当用作开漏输出时，需要使用一个上拉电阻器"。
  → PB5 配置 `GPIO_MODE_IT_FALLING` + `GPIO_PULLUP`（MCU 内部上拉兜底），**强烈建议外接 10 kΩ 到 3.3 V**。若不接上拉且无内部上拉，INT 永远为高 → 无中断。

### 5.4 协议 v1.2

三种帧，**统一 12 字节**，统一 CRC-8（多项式 0x07、初值 0x00、逐字节 XOR、无反射，覆盖字节 [2..10]）。

```
数据帧 TYPE = 0x55
 [0]=0xAA [1]=0x55 [2]=SEQ [3..4]=X_H/X_L [5..6]=Y [7..8]=Z [9..10]=TEMP [11]=CRC

状态帧 TYPE = 0x56
 [0]=0xAA [1]=0x56 [2]=SEQ
 [3]=PROTO_VER (0x12)
 [4]=FLAGS: bit0-1 RANGE(0=±40mT,1=±80mT,2=±120mT,3=±240mT)
          bit2 SENSOR_READY  bit3 CFG_OK
          bit4 TRIGGER_SRC(0=I2C,1=INT)  bit5 INT_PATH_OK
          bit6-7 保留
 [5..6]=SENS_LSB_PER_MT (uint16 BE)   ← 供 PC 端换算，修掉缺陷 B
 [7]=SAMPLE_RATE_HZ
 [8]=ERR_COUNT (累计 I2C 错误数)
 [9]=CONV_STATUS 原值
 [10]=DEVICE_STATUS 原值
 [11]=CRC

错误帧 TYPE = 0xEE
 [0]=0xAA [1]=0xEE [2]=SEQ [3]=ERR_CODE [4]=I2C_ADDR [5]=REG_ADDR
 [6..10]=保留(0) [11]=CRC
```

**错误码表（固件侧"规范状态码"的全部内容）：**

| Code | 宏名 | 触发条件 | 后果 |
|---|---|---|---|
| 0x00 | `ERR_NONE` | 初始化成功，传感器就绪 | 发一次；PC 端置"就绪" |
| 0x01 | `ERR_I2C_NACK` | `HAL_I2C_IsDeviceReady` 失败 | 进入降级：周期重试，仍持续发状态帧 |
| 0x02 | `ERR_SENSOR_ID` | 厂商 ID ≠ 0x4954 | 同上 |
| 0x03 | `ERR_CONFIG_FAIL` | 配置写入失败 | 同上 |
| 0x04 | `ERR_I2C_READ` | 采样期读失败 | 跳过本帧，继续 |
| 0x05 | `ERR_I2C_TIMEOUT` | I2C 事务超时 | 跳过本帧，继续 |
| 0x06 | `ERR_NO_CONV` | 触发后超时未拿到 Result_Status | 跳过本帧；状态帧置 INT_PATH_OK=0 |
| 0x07 | `ERR_SENSOR_DIAG` | `Conv_Status.Diag_Status` 置位（内部诊断失败） | 跳过本帧，继续 |
| 0x08 | `ERR_OVERFLOW` | `Device_Status` 溢出位置位 | 跳过本帧，继续 |
| 0x09 | `ERR_TX_OVERFLOW` | UART TX 队列溢出（丢帧） | 计数，PC 端可据此核对丢帧 |

**状态帧发送策略**：初始化完成后立即发一次；之后每 **1 s** 发一次心跳；任何状态变化（就绪↔故障、量程变更）立即发。

### 5.5 工程管理约定

- **`.ioc` 手工维护**：需补 PB5/EXTI5 与新引脚，但本项目**不执行 CubeMX "Generate Code"**（会重写 `main.c` 抹掉 `App/` 分层）。
  → `.ioc` 同步更新 PB5（`GPIO_MODE_IT`、`GPIO_PULLUP`、`EXTI5`、NVIC `EXTI5_IRQn`），并**手工**在 `main.c` / `stm32f4xx_it.c` 写等价代码，两者必须一致。若将来要用 CubeMX 生成，先手工把 `main.c` 的业务代码迁到 `App/`。
- **HAL/CMSIS 不入库**：CMake 从本机 CubeF4 包解析（§6.2）。

---

## 6. 构建与烧录

### 6.1 工具链结论

**编译：CMake 3.28.1 + Ninja + arm-none-eabi-gcc 14.3.1**（三者均在 CubeCLT 内且已入 PATH）。
**烧录：STM32CubeProgrammer CLI 2.22.0**（ST-Link 原生，一条命令，无需 OpenOCD 配置；OpenOCD 0.12.0 保留作 gdb 调试备选）。

```powershell
# 构建
cmake --preset Release      # 首次会自动 configure
cmake --build --preset Release

# 烧录 + 校验 + 复位
& 'C:\ST\STM32CubeCLT_1.21.0\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe' `
    -c port=SWD -w build/Release/TMA3001_.elf -v -rst
```

`tools/flash.ps1` 封装上述命令并做存在性检查；`tools/probe.ps1` 读芯片信息；`tools/build.ps1` 串联 configure + build。

### 6.2 HAL / CMSIS 定位（`cmake/firmware_sources.cmake`）

按顺序探测，命中即用：

1. `${CMAKE_SOURCE_DIR}/Drivers/STM32F4xx_HAL_Driver`（有人手工 vendored 时）
2. CMake 缓存变量 `STM32CUBE_F4_PATH`（默认 `C:/Users/Youko/STM32Cube/Repository/STM32Cube_FW_F4_V1.28.3`）
3. 环境变量 `STM32CUBE_F4_PATH`

三者都失败 → **CMake 直接报错并给出安装指引**（而不是静默编译失败）。HAL 源文件清单沿用 CubeMX 选定的 20 个模块，CMSIS 取 `Device/ST/STM32F4xx/Include` + `CMSIS/Include`。

### 6.3 `.gitignore`（用户明确要求："先写好 gitignore，只要传入关键代码"）

```gitignore
# ── 构建产物 ────────────────────────────────
build/  build-*/  cmake-build-*/
*.o  *.obj  *.elf  *.bin  *.hex  *.map  *.lst
compile_commands.json

# ── IDE / CubeMX ────────────────────────────
.idea/  .vscode/  *.iml  .mxproject  .clangd/
CMakeUserPresets.json

# ── ST 厂商代码（从本机 STM32Cube_FW_F4 解析）──
Drivers/STM32F4xx_HAL_Driver/
Drivers/CMSIS/

# ── PC 端 ────────────────────────────────────
host/build/  host/dist/  host/logs/
__pycache__/  *.py[cod]  .venv/
logs/  *.log

# ── 运行数据 ─────────────────────────────────
data/  *.csv
```

**入库**：App/、Core/、Drivers/Tmag3001/、Drivers/ST7789/、cmake/、tools/、host/、docs/、启动文件、链接脚本、`.ioc`、README。
**不入库**：HAL/CMSIS（ST 厂商代码，几百个文件）、构建产物、IDE 配置。

### 6.4 `Drivers/ST7789/` 的处置

保留在仓库（用户已写好的代码，且 `st7789-bugfix-postmortem.md` 记录了 5 个 DMA/CS 坑，有复用价值），但**不加入 CMake 源文件列表**，README 明确标注"屏幕支持暂缓，未参与构建"。

---

## 7. PC 端设计（`host/`）

### 7.1 模块划分

| 文件 | 职责 | 思想来源 |
|---|---|---|
| `color_scheme.py` | `ColorScheme` 类属性（唯一真相源，**零 Qt 导入**）+ `get_stylesheet()` + `hex_to_rgba()` | UI_palette `color_scheme.py` |
| `color_panel.py` | 右侧 170 px 颜色角色编辑面板，3 区域 | UI_palette `color_panel.py` |
| `plot_widgets.py` | pyqtgraph 图表（XYZ 叠加主图 + 温度副图）、滚动缓冲 | UI_palette `plot_widgets.py` |
| `main_window.py` | 布局、面板编排、快捷键 | UI_palette `main_window.py` |
| `settings_manager.py` | JSON 持久化（深度合并 + 原子写 + 未知键保留） | UI_palette `settings_manager.py` |
| `log_setup.py` | `setup_logging()`：时间戳文件 + 控制台双 handler | Logging_Standard §2 |
| `protocol.py` | 12 字节帧编解码 + CRC-8 + 状态码表 | TMAG3001_Protocol v1.2 |
| `serial_source.py` | 串口读取（QThread）+ 解析 + 丢帧统计 | 新写 |

### 7.2 颜色角色（UI_palette 思想的具体化）

11 个角色，分 3 类；派生色用 `_adjust(hex, amount)` 内联计算：

| 类别 | 角色 |
|---|---|
| 基础（5） | `TEXT` `LIGHT` `DARK` `LINE` `BTN` |
| 曲线（4） | `AXIS_X` `AXIS_Y` `AXIS_Z` `TEMP` |
| 显示（2） | `GRID` `AXIS` |

沿用 UI_palette 的关键决策：颜色用**类属性**而非字典（便于 QSS f-string 直接引用）；`get_stylesheet()` 是**函数**（每次重新读取属性）；QSS 应用于 `QApplication.instance()` 而非 `QMainWindow`；pyqtgraph 的 pen/brush 用 `hex_to_rgba()` 生成。

### 7.3 Logging_Standard 落地清单

| 规范条款 | 实现 |
|---|---|
| §2 `setup_logging()` | `log_setup.setup_logging("tmag_viewer", log_dir)`：文件 handler=DEBUG（含 `%(name)s:%(lineno)d`），控制台 handler=INFO，时间戳文件名 `tmag_viewer_YYYYmmdd_HHMMSS.log` |
| §3 模块级 logger | 每个模块 `logger = logging.getLogger(__name__)`，禁止硬编码名 |
| §11 传输层标记 | 串口相关行一律 `[transport=serial][addr=COM9@115200]` |
| §6 健康监控 | 每 30 s 一行 `HEALTH | uptime=%ds | rss=%.1fMB | cpu=%.1f%% | thr=%d | q=%d/%d | rate=%.1f/s | dropped=%d | err=%d` |
| §7 性能 | 采样回调（>100 Hz 路径）**不打日志**，只更新计数；日志按周期汇总 |
| §7 格式化 | 日志调用一律 `%s` 惰性格式化，**禁用 f-string** |
| §15 FILE_IO | CSV 保存：`tmp + os.replace` 原子写；行首 `FILE_IO | op=write kind=data path=...` |
| §4 状态转换 | 连接/断开/开始/停止记录含指标的 INFO 行 |
| §5 错误分级 | 串口异常 → `logger.exception`；帧 CRC 失败计数不刷屏 |

> §12 `USER_ACTION` 审计：单人本地工具，**本轮不实现**（保留字段位以便将来多人协作时接入）。

### 7.4 UI 布局

- 顶部：控制面板（串口选择 + 刷新 + 连接/断开 + 波特率 + 采样率显示 + 保存 CSV + 清屏 + Kalman 开关）
- 中部：`QSplitter` 纵向 —— XYZ 三曲线叠加主图（共享时间轴）+ 温度副图
- 右侧（170 px，可折叠）：颜色角色面板
- 底部（150 px，可折叠）：日志面板（最多 500 行）
- 状态栏：连接状态 / 传感器状态 / SEQ / 丢帧 / 实际帧率 / 量程+灵敏度（来自状态帧）
- 快捷键：`F10` 全屏，`Esc` 恢复（沿用 UI_palette）

---

## 8. 风险与应对

| # | 风险 | 影响 | 应对 |
|---|---|---|---|
| R1 | **PB5 无上拉**（INT 开漏） | EXTI 永不触发 | 配置 MCU 内部上拉；建议外接 10 kΩ；状态帧用 `INT_PATH_OK` 位告知 PC 端是否走通中断路径 |
| R2 | **ST-Link VCP 未接到 USART1 PA9/PA10** | 串口无输出 | 首次烧录先验证；若 COM9 静默，改用 USART2（PA2/PA3，屏幕不用后可用）—— 引脚集中在 `app_config.h` 一处切换 |
| R3 | 传感器未接 | 无数据帧 | 属正常验收档位：应收到 `ERR_I2C_NACK` + `SENSOR_READY=0` 状态帧，PC 端显示故障而非崩溃 |
| R4 | CubeCLT GCC 14.3.1 与原 CubeIDE 生成的代码有新版告警 | 可能编译失败 | `firmware_sources.cmake` 用 `-Wno-*` 精确豁免已知项，不整体关警告；不改动 CubeMX 生成的 HAL 胶水 |
| R5 | 115200 下 100 Hz 帧 + 状态帧 | 带宽不足 | 实测占用 10.4%，充裕；必要时 UART 提到 921600 |
| R6 | 量程/灵敏度在固件与 PC 端不一致（既有缺陷 B） | 数值全错 | 状态帧下发 SENS + RANGE，PC 端**不再硬编码** |

---

## 9. 验收标准

| ID | 标准 | 验证方式 |
|---|---|---|
| A1 | 干净检出后 `cmake --preset Release` 成功 configure 并编译出 `.elf`，无 error | 构建日志 |
| A2 | `tools/flash.ps1` 烧录成功并通过 `-v` 校验 | 烧录日志 |
| A3 | COM9 能读到**状态帧**（CRC 正确，字段自洽） | 串口抓包脚本 |
| A4 | 传感器接入后连续收到**数据帧**，SEQ 连续、无丢帧 | 抓包 + PC 端丢帧计数为 0 |
| A5 | PC 端显示 XYZ/温度曲线、量程/灵敏度与固件一致 | 截图 + 状态栏 |
| A6 | PC 端日志符合 Logging_Standard：含 `[transport=serial][addr=...]`、HEALTH 行、模块 logger、文件+控制台双输出 | 日志文件检查 |
| A7 | **未接传感器**时 PC 端显示明确故障状态，不崩溃、不空转 | 拔掉传感器重跑 |
| A8 | CSV 保存为原子写，中断后不留半截文件 | 文件检查 |
| A9 | `.gitignore` 生效：`git status` 不出现 HAL/CMSIS/build 产物 | `git status` |

---

## 10. 实施阶段

| 阶段 | 内容 | 出口条件 |
|---|---|---|
| P0 | 工程归集：复制关键文件、写 `.gitignore`、重写 CMake（HAL 定位）、写 build/flash/probe 脚本 | A1 |
| P1 | 固件：`App/` 分层、PB5/EXTI5、传感器配置、协议编码器、状态帧 | A2、A3 |
| P2 | PC 端：`host/` 模块化重构 | A5、A6 |
| P3 | 端到端联调 + 协议文档 v1.2 + README | A4、A7、A8、A9 |

---

## 11. 待用户确认的点

1. **PB5 是否有外部上拉电阻？** 若无，强烈建议加 10 kΩ（R1）。
2. **ST-Link VCP 走的是哪组 UART？** 若不是 USART1，需要改引脚（R2）。
3. **量程默认 ±40 mT（885 LSB/mT）是否合适？** 若传感器型号是 A2 变体，需切到 ±120/±240 mT。
4. **采样率 100 Hz 是否够？** 若要 200/500 Hz，需同步提高 UART 波特率或改二进制打包策略。
