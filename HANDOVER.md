# 交接文档：TMAG3001 × STM32F411 采集链路

> **2026-11-07 执行前更正**：v1.2（0x12）仍为待实现草案。线协议唯一契约是 `docs/protocol/TMAG3001_Protocol.md`，进度见 `docs/superpowers/plans/2026-11-07-execution-status.md`。CRC8/crc8/tmag_crc8 是遗留命名，算法仅为字节 XOR。


> **写给接手的主 agent。** 你没有产生本项目的任何对话历史，本文档 + 仓库内的三份设计/计划文档就是你的全部输入。
> **本文件是交接入口，先读它，再读 spec，最后读计划。**

---

## 0. 你的角色与工作方式

你是**主 agent**，按 `主 + 子 agent` 模式推进：

- 每个计划任务派一个**独立子 agent** 执行，子 agent 之间不共享上下文。
- 任务之间由你审阅把关（两阶段审阅：规格符合性 → 代码质量）。
- **不要**自己闷头写完所有任务；那样会失去并行收益和独立审阅的价值。

**建议的技能路由**（按顺序）：

1. 先 `skill` 加载 `superpowers:subagent-driven-development`（这是主+子模式的工作流定义）。
2. 需要批处理/断点续跑时加载 `superpowers:executing-plans`。
3. 需要独立审阅时用 `verifier` 类型的子 agent 做验收关卡。

**子 agent 的 prompt 必须自包含**（子 agent 看不到父对话）。把「本任务要做什么 + 相关文件路径 + 接口签名 + 验收命令」一次性写清楚，必要时直接贴计划里对应的代码块。

---

## 1. 仓库状态

| 项 | 值 |
|---|---|
| 路径 | `F:\youko_repo\Tmag3001_for_STM32F4_` |
| remote | `https://github.com/YoukoSaint/Tmag3001_for_STM32F4_` |
| 分支 | `codex/tmag-pipeline` —— 2026-11-07 由接手的 agent 从 `master` 切出并开始实施；`master` 已快进到同一 commit（`git branch -f master codex/tmag-pipeline`，纯 ref 更新，**不动工作区**） |
| HEAD | `772dfed docs(spec,plan,handover): 按 25MHz HSE 晶振修正时钟树` |
| 与远端 | `master` 比 `origin/master` **领先 5 个提交，全部未 push** |

提交历史：

```
772dfed  docs(spec,plan,handover): 按 25MHz HSE 晶振修正时钟树
893bafd  docs: 添加交接文档，供新主 agent 接手实施
6f71096  docs(plan): 添加固件与 PC 端两份实施计划
102560c  docs(spec): fold in user decisions and add sample-rate ceiling analysis
e770aff  docs: add F411 acquisition pipeline design spec
767a541  Realize the model acquisition of Tmag3001 magnetometer.   ← 原始提交
```

**关键背景**：`767a541`（GitHub 上原本的 master）只有 5 个文件（`main.c`/`main.h`/`tmag3001_driver.c/h`/`.ioc`），**没有 HAL、没有启动文件、没有链接脚本、没有 CMake，连编译都做不了**。后三个 commit 补齐了设计与计划。**固件代码尚未从本地遗产归集进仓库——那是 Plan A 的 Task 1。**

**未 push**：以上 4 个 commit 全部只在本地。是否推送由用户决定，不要擅自 push。

---

## 2. 必读文档（按此顺序）

| 顺序 | 文件 | 内容 |
|---|---|---|
| 1 | `HANDOVER.md`（本文件） | 事实、决策、约束、陷阱、执行协议 |
| 2 | `docs/superpowers/specs/2026-11-07-tmag3001-f411-pipeline-design.md` | 设计 spec（446 行）：现状盘点、寄存器真值、协议 v1.2、目录结构、风险表、验收标准 A1–A10 |
| 3 | `docs/superpowers/plans/2026-11-07-tmag3001-f411-firmware-pipeline.md` | **Plan A：固件主链路，9 个任务**（P0+P1） |
| 4 | `docs/superpowers/plans/2026-11-07-tmag3001-host-viewer.md` | **Plan B：PC 端，10 个任务**（P2+P3） |

**参考仓库**（只读，思想来源，不直接改代码）：

- `F:\youko_repo\UI_palette` —— PyQt5 动态配色系统（ColorScheme 类属性 / get_stylesheet() / hex_to_rgba() / 颜色面板 / 设置持久化）。Plan B 的 B4/B5/B8 借鉴它。
- `F:\youko_repo\Logging_Standard_for_Agent` —— `SKILL.md` + `AGENT_LOGGING_STANDARD_zh.md`。Plan B 的 B3/B6/B8 严格遵循它。

---

## 3. 已核实的事实（直接采信，不要重复调查）

### 3.1 工具链（全部实测可用）

| 工具 | 位置 / 版本 | 备注 |
|---|---|---|
| CMake | `C:\ST\STM32CubeCLT_1.21.0\CMake\bin\cmake.exe` → **3.28.1** | 已在 PATH |
| Ninja | `C:\ST\STM32CubeCLT_1.21.0\Ninja\bin\ninja.exe` | 已在 PATH |
| arm-none-eabi-gcc | `C:\ST\STM32CubeCLT_1.21.0\GNU-tools-for-STM32\bin\` → **14.3.1** | 已在 PATH |
| arm-none-eabi-gdb / objcopy / size | 同上目录 | 已在 PATH |
| STM32CubeProgrammer CLI | `C:\ST\STM32CubeCLT_1.21.0\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe` → **2.22.0** | 烧录用它 |
| ST-LINK GDB server | `C:\ST\STM32CubeCLT_1.21.0\STLink-gdb-server\bin\ST-LINK_gdbserver.exe` | 调试备选 |
| OpenOCD | `C:\OpenOCD-20250710-0.12.0\bin\openocd.exe` → 0.12.0 | **未入 PATH**，备选 |
| STM32Cube_FW_F4 | `C:\Users\Youko\STM32Cube\Repository\STM32Cube_FW_F4_V1.28.3` | 与 `.ioc` 声明的版本一致 |
| 宿主 C 编译器 | `C:\mingw64\bin\gcc.exe` → **MinGW-w64 GCC 15.2.0** | 已在 PATH（`gcc`），做宿主单测 |
| Python | `C:\ProgramData\Anaconda3\python.exe` → **3.9.12** | PyQt5 5.15.11 / pyqtgraph 0.13.7 / pyserial 3.5 / numpy 2.0.2 / psutil 5.8.0 / pytest 8.4.2 全装好 |

**注意**：`Get-Command make` 返回 NOT FOUND，但 `C:\mingw64\bin\mingw32-make.exe` 存在（GNU Make 4.4.1）。计划里**刻意不依赖 make**，直接调 gcc。

### 3.2 硬件（已实测识别）

| 项 | 值 |
|---|---|
| ST-Link | V2，SN `004800454A00001156313848`，FW `V2J46M33` |
| 目标芯片 | **STM32F411xC/E**（Device ID 0x431，512 KB Flash，Cortex-M4，3.24 V，Rev A） |
| ST-Link 虚拟串口 | **COM9**（`STLink Virtual COM Port`，制造商 STMicroelectronics） |
| 串口路由 | **USART1（PA9/PA10）@115200 8N1**（用户已确认） |
| 高速时钟晶振 | **HSE 25 MHz**，接 **PH0 (OSC_IN) / PH1 (OSC_OUT)**（用户 2026-11-07 确认） |

> `CLAUDE.md` 写的"串口在 COM3"是**错的**——COM3/COM7 是 Microsoft 虚拟口，COM9 才是 ST-Link VCP。

### 3.2b 时钟树：遗产固件根本没在用晶振（必须改）

**硬件**：板上 25 MHz HSE 晶振接在 **PH0 (OSC_IN) / PH1 (OSC_OUT)**。

**遗产 `main.c` 的 `SystemClock_Config()` 虽然跑 96 MHz，用的却是内部 RC**：

```c
RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;   /* ← 内部 RC */
RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;          /* ← PLL 源也是 HSI */
RCC_OscInitStruct.PLL.PLLM = 8;    /* 16/8  = 2 MHz  VCO in */
RCC_OscInitStruct.PLL.PLLN = 96;   /* 2×96  = 192 MHz VCO out */
RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;   /* → 96 MHz SYSCLK */
```

`.ioc` 同样自相矛盾：声明 `RCC.HSE_VALUE=25000000` + PH0/PH1 为 HSE 引脚，PLL 参数却按 HSI 推（`PLLM=8`、`VCOInputFreq_Value=2000000` = 16/8）。**25/8 = 3.125 MHz 非整数 —— HSE 下这个 PLLM 根本锁不上 PLL。**

**目标时钟树**（完整推导见 spec §5.1.1）：

| 环节 | 值 |
|---|---|
| HSE | 25 MHz（PH0/PH1） |
| PLLM / PLLN / PLLP / PLLQ | **25 / 192 / 2 / 4** → VCO in 1 MHz → VCO out 192 MHz → SYSCLK **96 MHz**；PLLQ 出 48 MHz |
| APB1 / APB2 | 48 MHz / 96 MHz |
| Flash / PWR | LATENCY 3 / VOS scale 1 |

**100 MHz 不可达**：PLLM 只能是 25；100 MHz 需 PLLN=400（VCO 400 MHz）→ PLLQ 凑不出 48 MHz（400/8=50、400/10=40），破坏 F411 的 USB 约束。**96 MHz 即本板上限** —— 频率与现在相同，只是把源从内部 RC 换成晶振。

**收益**：HSI 全范围 ±1% → 晶振 ±20–50 ppm。115200 波特率误差从 ±1152 bps 降到 ±6 bps，采样时基的长期稳定性同步改善。

**回退**：HSE 起振失败 → 自动回退 HSI（`PLLM=8 / PLLN=96 / PLLP=2 / PLLQ=4`，同为 96 MHz），并由状态帧 `FLAGS` bit6 `CLK_SRC_HSE=0` 上报"正在用内部 RC"。

**F411 没有 HSE 预分频器**：`RCC_OscInitTypeDef` 在 F411 上**没有 `HSEPredivValue` 字段**（F42x/43x 才有），写它直接编译失败。

### 3.3 TMAG3001 datasheet 结论（已逐页核对 81 页）

权威文档：**ZHCSR44C / SLYS053**（仓库内 `F:\Phd\20260325_Tmag3001_test\tmag3001.pdf`，中文版）。

| 寄存器 | 位 | 值 | 含义 |
|---|---|---|---|
| `Device_Config_1` (0x00) | `CRC_EN[7]` / `Conv_AVG[4:2]` / `I2C_RD[1:0]` | 0 / 0 / 0 | 禁用器件 CRC；1x 平均；标准读取 |
| `Device_Config_2` (0x01) | `Trigger_Mode[2]` / `Operating_Mode[1:0]` | **0** / 0 | **I2C 命令位触发转换**；待机/触发模式 |
| `Sensor_Config_1` (0x02) | `MAG_CH_EN[7:4]` | 0x70 | X/Y/Z 三通道 |
| `Sensor_Config_2` (0x03) | `T_Rate[7]` / `INTB_POL[6]` / `X_Y_Range[1]` / `Z_Range[0]` | 1 / **0** / 0 / 0 | 温度滤波；**中断低有效**；±40 mT |
| `INT_Config_1` (0x08) | `Result_INT[7]` / `INT_State[5]` / `INT_Mode[4:2]` / `INT_POL_EN[1]` / `MASK_INT[0]` | **1** / **0（锁存）** / 1 / 1 / 0 | 转换完成即中断；锁存而非 5µs 脉冲 |
| `Conv_Status` (0x18) | `Result_Status[0]` / `Diag_Status[1]` / `POR[4]` | — | 转换就绪 / 内部诊断失败 / 上电标志 |
| `Device_ID` (0x0D) | `Version[3:2]` | 0 | TMAG3001 ±40 mT |
| `Manufacturer_ID` (0x0E/0x0F) | — | 0x49 / 0x54 | 厂商 ID |

**灵敏度（固件与 PC 端都用这张表）**：

| 变体 | 量程 | LSB/mT |
|---|---|---|
| TMAG3001A1 | ±40 mT | **885** ← 本项目采用 |
| TMAG3001A1 | ±80 mT | 446 |
| TMAG3001A2 | ±120 mT | 273 |
| TMAG3001A2 | ±240 mT | 137 |

**温度换算**：`°C = (raw - 17512) / 58.2 + 25`（`T_ADC_T0=17512`，`58.2 LSB/°C`）。

**INT 引脚（datasheet §4 表 4-1）**：INT 是双向 IO——作**开漏输出**时**需要上拉电阻**；作**触发输入**时不需要。→ 本方案 INT 只做输出（data-ready），因此需要上拉。**用户已确认外接 10 kΩ 到 3.3 V**，MCU 侧仍配内部上拉兼底。

### 3.4 已证伪的既有资产（禁止复用）

| 资产 | 判定 |
|---|---|
| `F:\Phd\20260325_Tmag3001_test\...\Tmag3001\tmag3001_driver.c`（F407 版，15.7 KB，引用 SBAS993） | **寄存器映射与 datasheet 完全不符**（它把 `X_Result` 放 0x00、`Device_Config` 放 0x05；真值是 `Device_Config_1` 在 0x00、结果区在 0x10–0x1B）。**整体作废，禁止移植/混用。** |
| `F:\Phd\20260325_Tmag3001_test\...\Core\Src\main.c`（F407 版） | 只有纯文本 `snprintf` 输出，**没有协议编码器**。协议文档 v1.1 描述的二进制帧从未在固件实现过。 |
| `F:\Phd\20260325_Tmag3001_test` 整个目录 | F407 + CubeIDE 工程，与 F411 无关。 |
| `F:\Phd\20260330_Tmag3001\20260325_Tmag3001_test` | 上一条的副本（无 .git）。 |
| `F:\Phd\20260330_ Tmag3001` | 只有两个 TMAG3001 寄存器头文件的孤儿目录。 |

### 3.5 可复用资产

| 资产 | 位置 | 用途 |
|---|---|---|
| **F411 完整工程工作区** | `F:\Phd\GIT_YOUKOSAINT\TMA3001_` | 与 GitHub 同一 remote、同一 commit `767a541`，但工作区有 ~270 个未跟踪文件：完整 HAL、CMSIS、`STM32F411XX_FLASH.ld`、`startup_stm32f411xe.s`、CubeMX CMake 工程、`Drivers/ST7789/`（屏幕驱动 + 1.37 MB 字体 + 5 个 DMA/CS bug 复盘）、`Drivers/Tmag3001/`、已写好的 `Core/`。**这是 Plan A Task 1 的归集源。** |
| PC 端现有应用 | `F:\Phd\20260409_TMAG_3axis_visaulization\` | `tmag_viewer.py`（17.7 KB 可用 PyQt5 应用）、`TMAG3001_Protocol.md`（协议 v1.1 文档）、`TMAGViewer.spec`、`build.py`、`dist/TMAGViewer.exe` |
| F411 固件遗产 | `F:\Phd\GIT_YOUKOSAINT\TMA3001_\Drivers\Tmag3001\tmag3001_driver.c` | **正确的**（ZHCSR44C）驱动基线，Plan A Task 5 在它上面扩展 |
| 屏幕代码 | `F:\Phd\GIT_YOUKOSAINT\TMA3001_\Drivers\ST7789\` | 保留进仓库但**不参与构建**（本轮板子不做 UI） |
| CubeMX 陷阱笔记 | `F:\Phd\GIT_YOUKOSAINT\TMA3001_\CLAUDE.md`、`...\Drivers\ST7789\st7789-bugfix-postmortem.md` | SPI Mode 3、`-u _printf_float`、RGB565 memset 坑、CS 提前拉高坑 |

### 3.6 已完成的实测验证

- 遗留工程用 **CubeCLT GCC 14.3.1 零警告编译链接通过**（exit 0；text 129976 / data 496 / bss 3496）。→ 风险 R4 消解。
- `STM32_Programmer_CLI -l` 识别到 ST-Link V2；`-c port=SWD mode=HOTPLUG -r32 0xE000ED00 1` 读到 `0x410FC241`（Cortex-M4 CPUID）。
- CubeF4 V1.28.3 **有** `startup_stm32f411xe.s`（`Drivers/CMSIS/Device/ST/STM32F4xx/Source/Templates/gcc/`），但**没有 F411CEUx 的链接脚本**（只有 F411VE / F411RE 变体）→ `STM32F411XX_FLASH.ld` **必须随仓库提交**。
- PyQt5 offscreen 渲染可用；pytest / psutil / pyserial 均可用。

---

## 4. 已确认的用户决策（不要再问）

| # | 决策 | 结论 |
|---|---|---|
| D1 | PB5 上拉 | **外接 10 kΩ 到 3.3 V（已确认）**；MCU 内部上拉兼底 |
| D2 | ST-Link VCP 对应 UART | **USART1（PA9/PA10）**，不改引脚 |
| D3 | 量程 | **±40 mT（TMAG3001A1，885 LSB/mT）** |
| D4 | 采样率 | **上限以实测为准**（不预设）；默认起点 100 Hz，编译期可配置 |
| D5 | 板上 UI | **不做**。ST7789 代码保留在仓库但不参与构建 |
| D6 | 日志归属 | **全在 PC 端**；固件只发二进制帧与规范状态码 |
| D7 | Git 策略 | **先写好 `.gitignore`**；只提交关键代码；HAL/CMSIS 不入库（CMake 从本机 CubeF4 解析） |
| D8 | 工程根目录 | `F:\youko_repo\Tmag3001_for_STM32F4_`（**不在 `F:\youko_repo\` 根目录新增任何文件**） |
| D9 | 工具链 | CMake 3.28.1 + Ninja + arm-none-eabi-gcc 14.3.1（CubeCLT）；烧录 STM32CubeProgrammer CLI 2.22.0 |
| D10 | 执行模式 | **主 + 子 agent**（主 agent = 接手者，**不是本会话的 agent**） |
| D11 | 交接方式 | **本交接文档**；实施由另一个主 agent 推进 |
| D12 | 时钟源 | **改用 25 MHz HSE 晶振**（PH0/PH1）。`PLLM=25 / PLLN=192 / PLLP=2 / PLLQ=4` → SYSCLK 96 MHz、APB1 48 MHz、APB2 96 MHz、FLASH_LATENCY_3、VOS scale 1。HSE 起振失败自动回退 HSI（同为 96 MHz），状态帧 `FLAGS` bit6 `CLK_SRC_HSE` 上报。**100 MHz 不可达，96 MHz 即上限。** 详见 §3.2b |

---

## 5. 硬约束（红线）

1. **文件落位**：所有新文件必须在 `F:\youko_repo\Tmag3001_for_STM32F4_\` **之内**。禁止在 `F:\youko_repo\` 根目录新增文件。
2. **HAL / CMSIS 不入库**：`.gitignore` 必须排除 `Drivers/STM32F4xx_HAL_Driver/` 与 `Drivers/CMSIS/`；CMake 从 `STM32CUBE_F4_PATH` 解析。**禁止修改 HAL/CMSIS 任何文件。**
3. **链接脚本随仓库走**：`STM32F411XX_FLASH.ld` 必须提交（CubeF4 包里没有 F411CE 变体）。
4. **协议 v1.2 是契约**：三类帧统一 **12 字节**；`[0]=0xAA`；`[1]`=TYPE（`0x55` 数据 / `0x56` 状态 / `0xEE` 错误）；`[2]`=SEQ（0x00–0xFF 循环）；`[11]`=CRC-8（**初值 0x00、逐字节 XOR、无反射无反转，覆盖字节 `[2..10]` 共 9 字节**）。
5. **固件不发文本日志**，不发任何 `snprintf` 字符串；只发二进制帧。
6. **PC 端禁止硬编码灵敏度**（既不写 446 也不写 885）：必须从状态帧的 `SENS` 字段读取；未收到状态帧前不显示数值曲线。
7. **板上不做 UI**：CMake 源文件列表中不得出现 ST7789；`main.c` 里不得有 LCD 调用。
8. **不得执行 CubeMX "Generate Code"**：会重写 `main.c` 抹掉 `App/` 分层。`.ioc` 只作参考与未来再生成的来源。改 `.ioc` 时必须**手工**写等价的 `main.c` / `stm32f4xx_it.c` 代码，两边保持一致。
9. **采样率不得凭猜测写死**：默认 100 Hz，上限由 Plan A Task 8 扫频实测确定。
10. **寄存器映射一律以 ZHCSR44C 为准**，禁止引入 F407 驱动那份错误映射。
11. **文本文件编码 UTF-8 无 BOM**：禁止用 PowerShell 5.1 的 `Set-Content -Encoding UTF8`（会写 BOM 且可能破坏中文）。用 `write` 工具或 `[System.IO.File]::WriteAllText(path, text, (New-Object System.Text.UTF8Encoding($false)))`。
12. **不 push**，除非用户明确要求。
13. **不新增 Python 依赖**（PyQt5 / pyqtgraph / pyserial / numpy / psutil / pytest 已够）。
14. **不装系统软件**（winget/choco 等）除非用户明确批准。

---

## 6. 协议 v1.2 草案速查（以 canonical 协议文档为准）

```
所有帧 12 字节：[0]=0xAA  [1]=TYPE  [2]=SEQ  [3..10]=PAYLOAD  [11]=CRC8
CRC8 覆盖 [2..10]

数据帧 TYPE=0x55
  [3..4]=X(int16 BE, 原始 LSB)  [5..6]=Y  [7..8]=Z  [9..10]=TEMP(int16 BE)

状态帧 TYPE=0x56
  [3]=PROTO_VER=0x12
  [4]=FLAGS: bit0-1 RANGE(0=±40mT,1=±80mT,2=±120mT,3=±240mT)
            bit2 SENSOR_READY  bit3 CFG_OK
            bit4 TRIGGER_INT(1=INT 作转换触发输入，非 data-ready 输出)  bit5 INT_PATH_OK
            bit6 CLK_SRC_HSE(1=晶振,0=回退内部RC)  bit7 RATE_X10
  [5..6]=SENS_LSB_PER_MT (uint16 BE)   [7]=ENCODED_RATE（bit7=0: Hz；bit7=1: 10 Hz）
  [8]=ERR_COUNT  [9]=CONV_STATUS原值  [10]=DEVICE_STATUS原值

错误帧 TYPE=0xEE
  [3]=ERR_CODE  [4]=I2C_ADDR  [5]=REG_ADDR  [6..10]=0

错误码：0x00 NONE/READY  0x01 I2C_NACK  0x02 SENSOR_ID  0x03 CONFIG_FAIL
        0x04 I2C_READ  0x05 I2C_TIMEOUT  0x06 NO_CONV  0x07 SENSOR_DIAG
        0x08 OVERFLOW  0x09 TX_OVERFLOW
```

**五组跨语言 golden vector**（固件 C 与 PC 端 Python 必须给出相同字节）：

```
数据帧  seq=0x01 x=1496 y=44 z=-226 temp=17512
       AA 55 01 05 D8 00 2C FF 1E 44 68 3D
状态帧  seq=0x42 ver=0x12 flags=0x2C sens=885 rate=100 errcnt=0 conv=0x01 dev=0
       AA 56 42 12 2C 03 75 64 00 01 00 6F
状态帧  seq=0x42 rate=500（基础 flags=0x2C；线 flags=0xAC）
       AA 56 42 12 AC 03 75 32 00 01 00 B9
状态帧  seq=0x42 rate=1000（基础 flags=0x2C；线 flags=0xAC）
       AA 56 42 12 AC 03 75 64 00 01 00 EF
错误帧  seq=0x07 code=0x01 i2c=0x34 reg=0x0E
       AA EE 07 01 34 0E 00 00 00 00 00 3C
```

---

## 7. 执行计划：主 + 子 agent

### 7.1 推荐顺序

**先跑 Plan A 的 Task 1–8（固件），跑通并实机验证，再跑 Task 9 与 Plan B。**

理由：PC 端必须对着**真实**协议与**真实**采样率写；反过来先写 PC 端会对着臆测的参数返工。

### 7.2 任务依赖图（哪些能并行）

```
Plan A
  T1 仓库骨架与 .gitignore      ← 必须第一个（后续都依赖文件在仓库里）
  T2 CMake 重写 + HAL 外置解析   ← 依赖 T1
  T3 宿主单测基础设施            ← 依赖 T1（可与 T2 并行）
  T4 协议编解码器 + 单测         ← 依赖 T3
  T5 传感器驱动升级              ← 依赖 T2
  T6 应用层 + PB5/EXTI5         ← 依赖 T4 + T5
  T7 烧录/探测脚本 + 首次实机    ← 依赖 T6
  T8 采样率扫频                  ← 依赖 T7
  T9 协议文档 + README           ← 依赖 T8

Plan B
  B1 host 骨架 + pytest          ← 可与 Plan A 并行（只依赖协议文档）
  B2 协议层 + golden vector      ← 可与 Plan A 并行
  B3 log_setup / B4 color_scheme / B5 settings_manager
                                 ← 彼此独立，可与 B2 并行
  B6 serial_source + csv_writer  ← 依赖 B2
  B7 plot_widgets                ← 依赖 B4
  B8 color_panel + main_window   ← 依赖 B2/B4/B5/B6/B7
  B9 端到端验收                  ← 依赖 Plan A 的 T7/T8 与 B8
  B10 打包 + 文档                ← 最后
```

**建议批次**：

- 批次 1：T1（串行，必须先做）。
- 批次 2：T2 + T3 + B1 + B2 + B3 + B4 + B5（可并行派多个子 agent）。
- 批次 3：T4 + T5 + B6 + B7。
- 批次 4：T6。
- 批次 5：T7（需实机）。
- 批次 6：T8（需实机，需改 `APP_SAMPLE_RATE_HZ` 重编重烧）。
- 批次 7：T9 + B8。
- 批次 8：B9 + B10。

### 7.3 子 agent prompt 模板

每个子 agent 的 prompt 必须包含：

```
【目标】<一句话，对应计划中某个 Task 的标题>

【仓库】F:\youko_repo\Tmag3001_for_STM32F4_

【要读的计划章节】
docs/superpowers/plans/<文件名> 的 Task N（贴出该 Task 的完整内容，
或至少贴出该 Task 的 Steps 代码块）

【必须遵守的硬约束】
<从本文档第 5 节摘取与本任务相关的条目>

【接口契约】
<本任务产出/消费的函数签名、类型、结构体字段>

【验收命令】
<该 Task 的每个 Step 的 Run 命令与 Expected>

【禁止】
- 不要修改第 5 节列出的红线相关内容
- 不要 push
- 不要在 F:\youko_repo 根目录创建文件
- 不要改动 Drivers/STM32F4xx_HAL_Driver/ 与 Drivers/CMSIS/
- 不要删除 Drivers/ST7789/（只是不参与构建）

【输出】
完成后报告：改了哪些文件、跑了哪些命令、实际输出与 Expected 是否一致、
遇到的问题。
```

### 7.4 审阅关卡

每个任务结束后由你（主 agent）审阅：

1. **规格符合性**：是否做了计划要求的全部内容？验收命令是否真的跑过、输出是否符合 Expected？
2. **代码质量**：硬约束是否被违反？有没有引入未在计划里的额外改动？有没有把诊断代码留在提交里？

任一关卡不过 → 派一个新子 agent 修，不要自己接手改（保持上下文干净）。

---

## 8. 已知陷阱（都已踩过，务必规避）

| # | 陷阱 | 后果 | 规避 |
|---|---|---|---|
| T1 | `git commit -m "多行消息"` 且消息中有以 `-` 开头的行 | git 把 `- xxx` 当成参数/pathspec，提交失败（报 `pathspec '+' did not match`） | 用 `git commit -F <文件>`，消息文件用 UTF-8 **无 BOM** 写入 |
| T2 | 在 `%TEMP%` 下放 Python 脚本 | 该目录有残留 `inspect.py`，污染 stdlib 导入 → `ImportError: cannot import name 'currentframe'`；pyqtgraph 导入还会打出图像分析噪声 | **Python 脚本一律在仓库目录内运行** |
| T3 | 用 `robocopy /E` 做递归拷贝 | 被本地安全策略拦（"recursive write/delete target cannot be verified"） | 用 `Copy-Item` 逐目录拷；`tools/copy_legacy.ps1` 已写好 |
| T4 | CMake 的 `include(firmware_sources.cmake)` 放在 `add_executable()` 之后 | 变量未定义 → configure 直接失败 | `include()` 必须在 `add_executable()` **之前**（计划里已是正确顺序） |
| T5 | 由摄氏温度反推 `temp_raw` | 精度有损 | 驱动层 `TMAG3001_ReadSample()` 同事务保留 `temp_raw` 原始计数 |
| T6 | 温度/磁场的浮点 `printf` 在 newlib-nano 下不输出 | 静默无输出 | 链接加 `-u _printf_float -u _scanf_float`（计划已含） |
| T7 | 以为 COM3 是串口 | COM3/COM7 是 Microsoft 虚拟口 | ST-Link VCP = **COM9** |
| T8 | 在 `main.c` 里改 SPI/时钟而不改 `.ioc` | 下次 "Generate Code" 全部被覆盖 | 本项目**不执行 Generate Code**；改 `.ioc` 要手工同步代码 |
| T9 | 用 `Set-Content -Encoding UTF8` 改含中文的文件 | PS 5.1 写 BOM；某些组合会破坏中文源码 | 用 `write` 工具或 `WriteAllText` + `UTF8Encoding($false)` |
| T10 | `ST7789` 误参与构建 | text 涨到 130 KB 且白跑 SPI 初始化 | CMake 源文件列表不含 ST7789；`main.c` 不调 `MX_SPI1_Init` |
| T11 | 新增 `Drivers/ST7789` 到 git 之外误删 | 丢失用户已有工作 | 只"不参与构建"，**不删除** |
| T12 | 沿用遗产的 `PLLM=8 / PLLN=96` 却把 PLL 源切到 HSE | 25/8 = 3.125 MHz 非整数 → PLL 锁不上 → `HAL_RCC_OscConfig` 超时 → 板子"死了" | 切 HSE 必须**同时**改 `PLLM=25 / PLLN=192`（见 §3.2b） |
| T13 | 在 F411 上写 `RCC_OscInitStruct.HSEPredivValue = ...` | **编译失败** —— F411 没有这个字段（只有 F42x/43x 有） | 不写该字段；F411 的 HSE 无预分频器 |
| T14 | HSE 起振失败时直接 `Error_Handler()` | 晶振虚焊/板型不符 → 板子完全无响应，连串口都没有 | 必须回退 HSI（同为 96 MHz）并用状态帧 bit6 上报；spec 风险 R7 |

---

## 9. 硬件接线与实机操作

| TMAG3001 引脚 | → F411 | 说明 |
|---|---|---|
| VCC | 3.3 V | datasheet：1.65–3.6 V |
| GND | GND | |
| SCL | **PB6**（I2C1_SCL） | I2C1 @100 kHz（可提到 400 kHz / 1 MHz） |
| SDA | **PB7**（I2C1_SDA） | |
| ADDR | GND → 地址 0x34 | 固件启动扫描 0x34–0x37 自动适配 |
| INT | **PB5**（EXTI5，下降沿） | **外接 10 kΩ 上拉到 3.3 V（用户已接）** |

其他：USART1 PA9(TX)/PA10(RX) → ST-Link VCP → COM9；SWD PA13/PA14 → ST-Link。

**屏幕未接**（用户确认）：本轮不做任何板上 UI，不要初始化 SPI/显示。

**实机操作注意**：

- 烧录：`tools\flash.ps1 Release`（内部调 `STM32_Programmer_CLI -c port=SWD -w <elf> -v -rst`）。
- 抓包：`C:\ProgramData\Anaconda3\python.exe tools\hosttest\test_capture.py --port COM9 --seconds 10`。
- 烧录会复位目标板，属于预期行为。
- **传感器可能未接**：未接时固件应发 `ERR_I2C_NACK` 错误帧 + `SENSOR_READY=0` 的状态帧，这本身就是一个验收档位（spec A7），**不是故障**。

---

## 10. 验收标准

| ID | 标准 | 出处 |
|---|---|---|
| A1 | 干净检出后 `cmake --preset Release` 成功并产出 elf，无 error | Plan A T2 |
| A2 | `tools/flash.ps1` 烧录成功并通过 `-v` 校验 | Plan A T7 |
| A3 | COM9 能读到**状态帧**（CRC 正确、字段自洽） | Plan A T7 |
| A4 | 传感器接入后连续收到**数据帧**，SEQ 连续无丢帧 | Plan A T7 / Plan B B9 |
| A5 | PC 端显示 XYZ/温度曲线，量程与灵敏度与固件一致 | Plan B B9 |
| A6 | PC 端日志符合 Logging_Standard：`[transport=serial][addr=...]`、`HEALTH` 行、模块 logger、文件+控制台双输出 | Plan B B9 |
| A7 | **未接传感器**时 PC 端显示明确故障，不崩溃、不空转 | Plan B B9 |
| A8 | CSV 保存为原子写，无半截文件、无临时文件残留 | Plan B B9 |
| A9 | `.gitignore` 生效：`git status` 不出现 HAL/CMSIS/build 产物 | Plan A T1 |
| A10 | 采样率扫频有据：各档实测帧率/丢帧/瓶颈定位，据此确定默认工作点 | Plan A T8 |

---

## 11. 接手后的第一步

```
1. cd F:\youko_repo\Tmag3001_for_STM32F4_
2. git status                 # 确认工作区干净（有一个 build/ 探针目录属正常，.gitignore 会覆盖）
3. git log --oneline -n 5     # 交接基础893bafd；当前HEAD见实际日志，勿按旧6f71096回退
4. 读本文件 → 读 spec → 读 Plan A
5. 加载 skill: superpowers:subagent-driven-development
6. 派 Task 1 的子 agent（仓库骨架与 .gitignore），给出 7.3 模板化的 prompt
7. 审阅 → 通过后进入批次 2
```

**一个不要**：不要重新调查第 3 节的事实（工具链、datasheet、硬件）。都已实测确认，直接采信；把精力放在实现与审阅上。

**另一个不要**：不要在没有跑通固件链路（T7）之前先写 PC 端的主窗口。协议参数（灵敏度、采样率、量程）要以实机状态帧为准。

> 采样率统一补充：逻辑整数 0..255 直接编码；256..2550 仅精确 10 Hz 倍数可编码，其他值拒绝。0 表示未知/未配置。编码器从逻辑 Hz 重算并清/置 bit7，保留 bit6，由 range_code 重算 bits0-1。字段为名义配置 Hz，PC 以数据帧数/经过时间独立测实际 Hz。固件毫秒调度器更窄：`0 < rate <= 1000` 且 `1000 % rate == 0`，编译期拒绝其他配置；100/200/500/1000 Hz 可表示但尚未实测。SEQ 跨数据/状态/错误全部帧全局递增，丢帧检查覆盖全部有效帧。

> Device_Status 更正（datasheet §7.1.29，PDF第57页）：bit4 INT_RB、bit2 INT_ER、bit1 OTP_CRC_ER、bit0 THR_Cross，没有 overflow 位。0x08 OVERFLOW 仅保留兼容编号，无已证实溢出条件不得发出；THR_Cross/INT_RB 不得当溢出。INT_ER/OTP_CRC_ER 映射 ERR_SENSOR_DIAG。Task5/6 必须读取并上报实际 Device_Status，不得始终发送初始化0；需驱动/应用测试验证。
