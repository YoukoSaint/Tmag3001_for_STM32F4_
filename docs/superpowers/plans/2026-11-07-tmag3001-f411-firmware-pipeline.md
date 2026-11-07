# TMAG3001 × STM32F411 固件采集链路 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把仓库从"只有 5 个文件、连编译都做不了"改造成可构建、可烧录的 STM32F411 固件，实现 PB5/EXTI5 驱动的 TMAG3001 采集与 12 字节二进制协议输出，并实测出采样率上限。

**Architecture:** 固件分为三层——`Drivers/Tmag3001`（寄存器级驱动，HAL 依赖）、`App/`（应用层：采样状态机 + 协议编解码，纯 C 不依赖 HAL）、`Core/`（CubeMX 生成的 HAL 胶水与薄壳 `main.c`）。协议编解码器 `App/Src/tmag_proto.c` **不依赖 HAL**，因此可用宿主 MinGW GCC 做真单元测试；固件与 PC 端共享同一份帧格式定义。

**Tech Stack:** STM32F411CEU6 · STM32Cube HAL (FW_F4 V1.28.3) · CMake 3.28.1 + Ninja · arm-none-eabi-gcc 14.3.1 (STM32CubeCLT 1.21.0) · STM32CubeProgrammer CLI 2.22.0 · 宿主测试用 MinGW-w64 GCC 15.2.0

**Design Spec:** `docs/superpowers/specs/2026-11-07-tmag3001-f411-pipeline-design.md`

---

## Global Constraints

以下每条都是硬约束，任何任务都不得违反（抄自 spec，值逐字一致）：

- **MCU**：STM32F411CEU6（UFQFPN48），512 KB Flash / 128 KB RAM。
- **传感器**：TMAG3001A1，量程 **±40 mT**，灵敏度 **885 LSB/mT**；I2C 地址由 ADDR 引脚决定，启动时扫描 `0x34–0x37`。
- **寄存器映射**：一律以 datasheet **ZHCSR44C / SLYS053** 为准。**禁止**使用 `F:\Phd\20260325_Tmag3001_test` 中那份 F407 驱动的寄存器映射（它是错的）。
- **INT 引脚**：传感器 INT → **PB5 / EXTI5 下降沿**；**外接 10 kΩ 上拉到 3.3 V 已确认存在**；MCU 侧仍配置内部上拉兼底。
- **传感器工作配置**：`Operating_Mode=0`（待机/触发）、`Trigger_Mode=0`（I2C 命令位触发转换）、`INT_Mode=1`、`Result_INT=1`、`INT_State=0`（锁存）、`INT_POL_EN=1`、`MASK_INT=0`、`INTB_POL=0`（中断低有效）、`T_Rate=1`、`MAG_CH_EN=0x70`（X/Y/Z）、`X_Y_Range=0`、`Z_Range=0`、`Conv_AVG=0`、`CRC_EN=0`、`I2C_RD=0`。
- **UART**：USART1（PA9/PA10）@ **115200 8N1**，DMA2_Stream7 发送；ST-Link VCP → **COM9**。
- **时钟**：**HSE 25 MHz 晶振**（PH0/PH1）→ `PLLM=25 / PLLN=192 / PLLP=2 / PLLQ=4` → **SYSCLK 96 MHz**、APB1 48 MHz、APB2 96 MHz、FLASH_LATENCY_3、PWR VOS scale 1。**HSE 起振失败自动回退 HSI**（同为 96 MHz），经状态帧 `FLAGS` bit6 `CLK_SRC_HSE` 上报。**100 MHz 不可达**（PLLQ 凑不出 48 MHz，96 MHz 即本板上限）。**F411 的 `RCC_OscInitTypeDef` 没有 `HSEPredivValue` 字段（F42x/43x 才有），写它会编译失败。** 详见 spec §5.1.1。
- **协议 v1.2**：三类帧**统一 12 字节**。`[0]=0xAA` 同步头；`[1]` 为 TYPE（`0x55` 数据 / `0x56` 状态 / `0xEE` 错误）；`[2]` 为 SEQ（0x00–0xFF 循环）；`[11]` 为 CRC-8。**CRC-8 = 初值 0x00、逐字节 XOR、无反射无反转，覆盖字节 `[2..10]` 共 9 字节**（等价于多项式 0x07 的 MPEG-2 写法）。
- **采样率**：编译期可配置，默认 **100 Hz**；**上限以 P1 扫频实测为准**（验收项 A10），不得凭猜测写死。
- **固件职责边界**：固件**只发二进制帧**，不发任何文本日志。所有日志、诊断、可视化在 PC 端。
- **HAL / CMSIS 不入库**：由 CMake 从本机 `STM32Cube_FW_F4_V1.28.3` 解析。**禁止**把 `Drivers/STM32F4xx_HAL_Driver/`、`Drivers/CMSIS/` 加入 git。
- **链接脚本**：CubeF4 V1.28.3 **不含** F411CEUx 变体（只有 F411VE / F411RE），因此 `STM32F411XX_FLASH.ld` **必须随仓库提交**；`startup_stm32f411xe.s` 可从 CubeF4 包取，但仓库也保留一份以便离线构建。
- **板上不做 UI**：`Drivers/ST7789/` 代码**保留在仓库但不参与构建**（CMake 源文件列表中不得出现）。
- **文件落位**：所有新文件必须位于 `F:\youko_repo\Tmag3001_for_STM32F4_\` **之内**；**禁止**在 `F:\youko_repo\` 根目录新增任何文件。
- **不修改 HAL/CMSIS 任何文件**。
- **文本文件编码**：一律 UTF-8 **无 BOM**（PowerShell 5.1 的 `Set-Content -Encoding UTF8` 会写 BOM，禁止使用；用 `write` 工具或 `[System.IO.File]::WriteAllText` + `UTF8Encoding($false)`）。
- **提交粒度**：每个任务结束提交一次，提交信息用 `git commit -F <文件>`（不要用 `git commit -m`，多行消息中以 `-` 开头的行会被 git 误解析为参数——已踩过这个坑）。

---

## File Structure

### 新建

| 路径 | 职责 |
|---|---|
| `.gitignore` | 排除 HAL/CMSIS、构建产物、IDE 配置、PC 端产物 |
| `README.md` | 工具链、构建、烧录、串口速查；协议摘要；屏幕支持暂缓说明 |
| `cmake/firmware_sources.cmake` | 定位 HAL/CMSIS（vendored → cache 变量 → 环境变量），列出源文件，失败即报错并给指引 |
| `App/Inc/app.h` | 应用层对外接口：`App_Init` / `App_Process` / `App_OnSensorInt` |
| `App/Inc/app_config.h` | 采样率、量程、I2C 扫描范围、超时、状态周期等所有可调常量（单一真相源） |
| `App/Inc/tmag_proto.h` | 协议常量、帧类型、错误码、状态位、数据结构、编解码 API |
| `App/Src/app.c` | 初始化流程、采样状态机、EXTI 回调、帧调度 |
| `App/Src/tmag_proto.c` | CRC-8 与三种帧的编码（**纯 C，无 HAL 依赖**） |
| `tools/build.ps1` | configure + build 一键脚本 |
| `tools/flash.ps1` | STM32CubeProgrammer CLI 烧录 + 校验 + 复位 |
| `tools/probe.ps1` | 读芯片信息 / 复位 |
| `tools/hosttest/run_tests.ps1` | 宿主单元测试入口（直接调 gcc，不依赖 make） |
| `tools/hosttest/test_harness.h` | 极简断言宏 + 计数 |
| `tools/hosttest/test_proto.c` | 协议编解码单元测试 |
| `tools/hosttest/test_capture.py` | 串口抓包脚本：解帧、打印、统计丢帧（用于 A3/A4/A10） |
| `docs/protocol/TMAG3001_Protocol.md` | 协议 v1.2 正式文档 |

### 修改

| 路径 | 改动 |
|---|---|
| `CMakeLists.txt` | 重写：不再 `add_subdirectory(cmake/stm32cubemx)`，改为引入 `firmware_sources.cmake`；不加 ST7789 |
| `CMakePresets.json` | 增加 `STM32CUBE_F4_PATH` cache 变量；保留 Ninja 生成器 |
| `Core/Src/main.c` | 重写为薄壳：HAL/时钟/外设初始化 + `App_Init` + 主循环调 `App_Process`；**删除全部 LCD 与 ST7789 调用** |
| `Core/Src/stm32f4xx_it.c` | 新增 `EXTI5_IRQHandler` → `HAL_GPIO_EXTI_IRQHandler(GPIO_PIN_5)` |
| `Core/Src/stm32f4xx_hal_msp.c` | USART1 TX DMA 保留；确认 `MX_GPIO_Init` 里 PB5 配 EXTI5 + 内部上拉 + NVIC 使能 |
| `Core/Inc/main.h` | 新增 `INT1_Pin`（PB5）宏与 `EXTI5_IRQn` 相关声明 |
| `Drivers/Tmag3001/tmag3001_driver.c` / `.h` | 新增 INT 配置 API、I2C 触发写、9 字节批量读、量程→灵敏度映射；保留原 API 兼容 |

### 复制（源：`F:\Phd\GIT_YOUKOSAINT\TMA3001_`，**不复制 HAL/CMSIS**）

`Core/`（Inc+Src 全部）、`Drivers/Tmag3001/`、`Drivers/ST7789/`、`cmake/gcc-arm-none-eabi.cmake`、`cmake/starm-clang.cmake`、`CMakeLists.txt`、`CMakePresets.json`、`startup_stm32f411xe.s`、`STM32F411XX_FLASH.ld`、`TMA3001_.ioc`

---

### Task 1: 仓库骨架与 .gitignore

**Files:**
- Create: `.gitignore`
- Create: `tools/copy_legacy.ps1`（一次性归集脚本，幂等）
- Modify: 仓库根（复制进来）

**Interfaces:**
- Consumes: 无
- Produces: 仓库内具备 `Core/`、`Drivers/Tmag3001/`、`Drivers/ST7789/`、`cmake/gcc-arm-none-eabi.cmake`、`cmake/starm-clang.cmake`、`startup_stm32f411xe.s`、`STM32F411XX_FLASH.ld`、`TMA3001_.ioc`；`.gitignore` 生效。后续所有任务都基于此骨架。

- [ ] **Step 1: 写 .gitignore**

内容（逐字）：

```gitignore
# ── 构建产物 ────────────────────────────────
build/
build-*/
cmake-build-*/
*.o
*.obj
*.elf
*.bin
*.hex
*.map
*.lst
compile_commands.json

# ── IDE / CubeMX ────────────────────────────
.idea/
.vscode/
*.iml
.mxproject
.clangd/
CMakeUserPresets.json

# ── ST 厂商代码（从本机 STM32Cube_FW_F4 解析，不入库）──
Drivers/STM32F4xx_HAL_Driver/
Drivers/CMSIS/

# ── PC 端 ────────────────────────────────────
host/build/
host/dist/
host/logs/
__pycache__/
*.py[cod]
.venv/
logs/
*.log

# ── 运行数据 ─────────────────────────────────
data/
*.csv
```

- [ ] **Step 2: 写归集脚本 `tools/copy_legacy.ps1`**

```powershell
# 一次性把本地遗产的关键代码归集进仓库（幂等，可重复执行）
$ErrorActionPreference = 'Stop'
$src = 'F:\Phd\GIT_YOUKOSAINT\TMA3001_'
$dst = 'F:\youko_repo\Tmag3001_for_STM32F4_'

if (-not (Test-Path $src)) { throw "legacy source not found: $src" }

# 目录：注意只取 Drivers 下的两个自有目录，绝不取 HAL/CMSIS
$dirs = @(
    'Core',
    'Drivers\Tmag3001',
    'Drivers\ST7789',
    'cmake'
)
foreach ($d in $dirs) {
    $from = Join-Path $src $d
    $to   = Join-Path $dst $d
    if (-not (Test-Path $to)) { New-Item -ItemType Directory -Force -Path $to | Out-Null }
    Copy-Item -Path (Join-Path $from '*') -Destination $to -Recurse -Force
    Write-Output "copied dir  $d"
}

# 单文件
$files = @(
    'CMakeLists.txt',
    'CMakePresets.json',
    'startup_stm32f411xe.s',
    'STM32F411XX_FLASH.ld',
    'TMA3001_.ioc'
)
foreach ($f in $files) {
    Copy-Item -Path (Join-Path $src $f) -Destination (Join-Path $dst $f) -Force
    Write-Output "copied file $f"
}

Write-Output 'done. NOTE: cmake/stm32cubemx/ is intentionally NOT copied (replaced in Task 2).'
```

- [ ] **Step 3: 执行归集**

Run: `powershell -ExecutionPolicy Bypass -File F:\youko_repo\Tmag3001_for_STM32F4_\tools\copy_legacy.ps1`
Expected: 输出 4 条 `copied dir` + 5 条 `copied file` + `done.`

- [ ] **Step 4: 验证骨架落地且 HAL/CMSIS 未混入**

Run:
```powershell
Get-ChildItem 'F:\youko_repo\Tmag3001_for_STM32F4_' -Force | Select-Object -ExpandProperty Name
Test-Path 'F:\youko_repo\Tmag3001_for_STM32F4_\Drivers\STM32F4xx_HAL_Driver'
Test-Path 'F:\youko_repo\Tmag3001_for_STM32F4_\Drivers\CMSIS'
```
Expected: 第一行列出 `App`(尚不存在，正常)、`Core`、`Drivers`、`cmake`、`docs`、`tools`、`.gitignore`、`CMakeLists.txt`、`CMakePresets.json`、`startup_stm32f411xe.s`、`STM32F411XX_FLASH.ld`、`TMA3001_.ioc`；后两行均为 **False**。

- [ ] **Step 5: 确认 .gitignore 生效**

Run: `git -C F:\youko_repo\Tmag3001_for_STM32F4_ status --short`
Expected: 输出中**不含** `Drivers/STM32F4xx_HAL_Driver/` 或 `Drivers/CMSIS/` 任何条目；应看到 `Core/`、`Drivers/Tmag3001/`、`Drivers/ST7789/`、`cmake/`、`tools/`、`CMakeLists.txt` 等待新增项。

- [ ] **Step 6: 提交**

```bash
git add .gitignore tools/copy_legacy.ps1 Core Drivers/Tmag3001 Drivers/ST7789 cmake CMakeLists.txt CMakePresets.json startup_stm32f411xe.s STM32F411XX_FLASH.ld TMA3001_.ioc
git commit -F .git_commit_msg.txt
```

提交信息（写入 `.git_commit_msg.txt`，UTF-8 无 BOM）：

```
chore: 归集本地 F411 遗产进仓库并加 .gitignore

从 F:\Phd\GIT_YOUKOSAINT\TMA3001_ 归集关键代码：Core/、Drivers/Tmag3001/、
Drivers/ST7789/、cmake/、启动文件、链接脚本、.ioc。

.gitignore 排除 HAL/CMSIS（从本机 STM32Cube_FW_F4 解析）、构建产物、
IDE 配置。ST7789 保留在仓库但本轮不参与构建。
```

> 提交前确认 `.git_commit_msg.txt` 本身不会被提交（它不在 `.gitignore` 中，提交后立即删除该临时文件）。

---

### Task 2: CMake 重写与 HAL/CMSIS 外置解析

**Files:**
- Create: `cmake/firmware_sources.cmake`
- Modify: `CMakeLists.txt`（完全重写）
- Modify: `CMakePresets.json`
- Create: `tools/build.ps1`

**Interfaces:**
- Consumes: Task 1 的骨架
- Produces: `cmake --preset Release` 能 configure + build 成功，产出 `build/Release/TMA3001_.elf`。后续所有任务都依赖这个构建链。

- [ ] **Step 1: 写 `cmake/firmware_sources.cmake`**

```cmake
# ──────────────────────────────────────────────────────────────
#  定位 STM32 HAL / CMSIS，并列出固件源文件
#
#  探测顺序：
#    1. 仓库内 vendored 副本（Drivers/STM32F4xx_HAL_Driver）
#    2. CMake 缓存变量 STM32CUBE_F4_PATH
#    3. 环境变量 STM32CUBE_F4_PATH
#  三者都失败 → 立即报错并给出安装指引（不静默失败）
# ──────────────────────────────────────────────────────────────

set(STM32CUBE_F4_PATH "" CACHE PATH "STM32Cube FW_F4 package root (contains Drivers/)")

# 候选 1：仓库内 vendored
set(_hal_candidate "${CMAKE_CURRENT_SOURCE_DIR}/Drivers/STM32F4xx_HAL_Driver")

# 候选 2/3：缓存变量或环境变量
if(NOT STM32CUBE_F4_PATH AND DEFINED ENV{STM32CUBE_F4_PATH})
    set(STM32CUBE_F4_PATH "$ENV{STM32CUBE_F4_PATH}")
endif()

if(NOT "${_hal_candidate}" STREQUAL "" AND EXISTS "${_hal_candidate}/Src")
    set(STM32_HAL_ROOT "${_hal_candidate}")
    set(STM32_CMSIS_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/Drivers/CMSIS")
    message(STATUS "STM32 HAL  : ${STM32_HAL_ROOT} (vendored)")
elseif(STM32CUBE_F4_PATH AND EXISTS "${STM32CUBE_F4_PATH}/Drivers/STM32F4xx_HAL_Driver/Src")
    set(STM32_HAL_ROOT "${STM32CUBE_F4_PATH}/Drivers/STM32F4xx_HAL_Driver")
    set(STM32_CMSIS_ROOT "${STM32CUBE_F4_PATH}/Drivers/CMSIS")
    message(STATUS "STM32 HAL  : ${STM32_HAL_ROOT} (STM32CUBE_F4_PATH)")
else()
    message(FATAL_ERROR
        "找不到 STM32F4 HAL。\n"
        "请任选其一：\n"
        "  1) 安装 STM32Cube FW_F4 V1.28.3，然后：\n"
        "     cmake --preset Release -DSTM32CUBE_F4_PATH=C:/Users/Youko/STM32Cube/Repository/STM32Cube_FW_F4_V1.28.3\n"
        "  2) 设置环境变量 STM32CUBE_F4_PATH 指向该包根目录\n"
        "  3) 或把 HAL/CMSIS 手工拷进仓库的 Drivers/ 下（注意此时不要提交它们）")
endif()

if(NOT EXISTS "${STM32_CMSIS_ROOT}/Device/ST/STM32F4xx/Include/stm32f411xe.h")
    message(FATAL_ERROR "CMSIS device header not found under ${STM32_CMSIS_ROOT}")
endif()

# ── HAL 源文件清单（与 CubeMX 原工程选择的 20 个模块一致）──
set(STM32_HAL_SOURCES
    stm32f4xx_hal_i2c.c
    stm32f4xx_hal_i2c_ex.c
    stm32f4xx_hal_rcc.c
    stm32f4xx_hal_rcc_ex.c
    stm32f4xx_hal_flash.c
    stm32f4xx_hal_flash_ex.c
    stm32f4xx_hal_flash_ramfunc.c
    stm32f4xx_hal_gpio.c
    stm32f4xx_hal_dma.c
    stm32f4xx_hal_dma_ex.c
    stm32f4xx_hal_pwr.c
    stm32f4xx_hal_pwr_ex.c
    stm32f4xx_hal_cortex.c
    stm32f4xx_hal.c
    stm32f4xx_hal_exti.c
    stm32f4xx_hal_spi.c
    stm32f4xx_hal_tim.c
    stm32f4xx_hal_tim_ex.c
    stm32f4xx_hal_uart.c
)
list(TRANSFORM STM32_HAL_SOURCES PREPEND "${STM32_HAL_ROOT}/Src/" OUTPUT_VARIABLE STM32_HAL_SOURCES)

# ── 应用层与用户代码 ──
set(APP_SOURCES
    "${CMAKE_CURRENT_SOURCE_DIR}/Core/Src/main.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/Core/Src/stm32f4xx_it.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/Core/Src/stm32f4xx_hal_msp.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/Core/Src/system_stm32f4xx.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/Core/Src/syscalls.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/Core/Src/sysmem.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/App/Src/app.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/App/Src/tmag_proto.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/Drivers/Tmag3001/tmag3001_driver.c"
)

set(APP_INCLUDES
    "${CMAKE_CURRENT_SOURCE_DIR}/Core/Inc"
    "${STM32_HAL_ROOT}/Inc"
    "${STM32_HAL_ROOT}/Inc/Legacy"
    "${STM32_CMSIS_ROOT}/Device/ST/STM32F4xx/Include"
    "${STM32_CMSIS_ROOT}/Include"
    "${CMAKE_CURRENT_SOURCE_DIR}/App/Inc"
    "${CMAKE_CURRENT_SOURCE_DIR}/Drivers/Tmag3001"
)
```

- [ ] **Step 2: 重写 `CMakeLists.txt`**

```cmake
cmake_minimum_required(VERSION 3.22)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS TRUE)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE "Release")
endif()

set(CMAKE_PROJECT_NAME TMA3001_)
project(${CMAKE_PROJECT_NAME})

enable_language(C ASM)

# 必须早于 add_executable()：firmware_sources.cmake 定义了
# APP_SOURCES / APP_INCLUDES / STM32_HAL_SOURCES 三个变量
include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/firmware_sources.cmake)

add_executable(${CMAKE_PROJECT_NAME}
    ${APP_SOURCES}
    ${STM32_HAL_SOURCES}
    "${CMAKE_CURRENT_SOURCE_DIR}/startup_stm32f411xe.s"
)

target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE ${APP_INCLUDES})

target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
    USE_HAL_DRIVER
    STM32F411xE
    $<$<CONFIG:Debug>:DEBUG>
)

list(REMOVE_ITEM CMAKE_C_IMPLICIT_LINK_LIBRARIES ob)

target_link_libraries(${CMAKE_PROJECT_NAME}
    m
    nosys
)

# newlib-nano 的 printf 不含浮点支持，必须显式链接 _printf_float
target_link_options(${CMAKE_PROJECT_NAME} PRIVATE
    -u _printf_float
    -u _scanf_float
)

# 链接脚本：F411CEUx 变体不在 STM32Cube_FW_F4 包内，必须随仓库走
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -T \"${CMAKE_CURRENT_SOURCE_DIR}/STM32F411XX_FLASH.ld\" --specs=nano.specs -Wl,--gc-sections -Wl,-Map=${CMAKE_PROJECT_NAME}.map")
```

- [ ] **Step 3: 改 `CMakePresets.json`**

在 `cacheVariables` 中加入：

```json
"cacheVariables": {
    "STM32CUBE_F4_PATH": "$env{STM32CUBE_F4_PATH}"
}
```

并在文件末尾新增一个预设（若 `$env{...}` 未定义导致 configure 报错，则用下面的显式预设替代）：

```json
{
    "name": "Release-local",
    "inherits": "Release",
    "cacheVariables": {
        "STM32CUBE_F4_PATH": "C:/Users/Youko/STM32Cube/Repository/STM32Cube_FW_F4_V1.28.3"
    }
}
```

- [ ] **Step 4: 写 `tools/build.ps1`**

```powershell
# 一键构建：configure + build
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$preset = if ($args.Count -ge 1) { $args[0] } else { 'Release' }

$cmake = (Get-Command cmake -ErrorAction SilentlyContinue)
if (-not $cmake) { throw 'cmake not found in PATH' }

Write-Output "=== configure (preset=$preset) ==="
& $cmake.Source --preset $preset -S $repo
if ($LASTEXITCODE -ne 0) { throw "cmake configure failed ($LASTEXITCODE)" }

Write-Output "=== build ==="
& $cmake.Source --build --preset $preset
if ($LASTEXITCODE -ne 0) { throw "cmake build failed ($LASTEXITCODE)" }

$elf = Join-Path $repo "build\$preset\TMA3001_.elf"
if (Test-Path $elf) {
    Write-Output "=== artifact ==="
    & arm-none-eabi-size $elf
    Write-Output "OK: $elf"
} else {
    throw "expected elf not found: $elf"
}
```

- [ ] **Step 5: 首次 configure + build（此时 App/ 还不存在，必须先造占位）**

Task 2 的 CMakeLists 引用了 `App/Src/app.c` 与 `App/Src/tmag_proto.c`，而它们在 Task 4/6 才创建。为让 Task 2 可独立验证，先创建**最小占位**（后续任务会整体替换）：

`App/Src/app.c`：
```c
#include "app.h"
void App_Init(void) {}
void App_Process(void) {}
void App_OnSensorInt(void) {}
```

`App/Inc/app.h`：
```c
#ifndef APP_H
#define APP_H
#include <stdint.h>
void App_Init(void);
void App_Process(void);
void App_OnSensorInt(void);
#endif
```

`App/Src/tmag_proto.c`：
```c
#include "tmag_proto.h"
```

`App/Inc/tmag_proto.h`：
```c
#ifndef TMAG_PROTO_H
#define TMAG_PROTO_H
#include <stdint.h>
#endif
```

Run: `powershell -ExecutionPolicy Bypass -File F:\youko_repo\Tmag3001_for_STM32F4_\tools\build.ps1 Release`
Expected:
- configure 阶段打印 `STM32 HAL  : .../STM32Cube_FW_F4_V1.28.3/Drivers/STM32F4xx_HAL_Driver (STM32CUBE_F4_PATH)`
- build 成功
- 打印 `text/data/bss` 尺寸，末尾 `OK: ...\build\Release\TMA3001_.elf`

> 若 configure 因 `$env{STM32CUBE_F4_PATH}` 未定义而失败，改用 `Release-local` 预设。

- [ ] **Step 6: 提交**

```
chore(cmake): 重写构建系统，HAL/CMSIS 从 STM32Cube_FW_F4 外置解析

- 新增 cmake/firmware_sources.cmake：三级探测 HAL/CMSIS 位置，失败即报错给指引
- CMakeLists 改为自维护结构，不再依赖 CubeMX 生成的 cmake/stm32cubemx
- 源文件列表不含 ST7789（板上不做 UI）
- 链接脚本 STM32F411XX_FLASH.ld 随仓库走：CubeF4 V1.28.3 只有 F411VE/F411RE 变体
- 新增 tools/build.ps1 一键 configure+build
- 新增 App/ 最小占位（Task 4/6 替换）
```

---

### Task 3: 宿主单元测试基础设施

**Files:**
- Create: `tools/hosttest/run_tests.ps1`
- Create: `tools/hosttest/test_harness.h`
- Create: `tools/hosttest/test_proto.c`（Task 4 填充内容，此处先建空壳）

**Interfaces:**
- Consumes: Task 2 的骨架
- Produces: `powershell -File tools/hosttest/run_tests.ps1` 可运行并输出 `OK: N/N passed`；后续任务用它做协议层的 TDD。

- [ ] **Step 1: 写 `tools/hosttest/test_harness.h`**

```c
#ifndef TEST_HARNESS_H
#define TEST_HARNESS_H

#include <stdio.h>

static int g_checks = 0;
static int g_failures = 0;

#define CHECK(cond, ...)                                                   \
    do {                                                                    \
        g_checks++;                                                         \
        if (!(cond)) {                                                      \
            g_failures++;                                                   \
            printf("FAIL %s:%d: ", __FILE__, __LINE__);                      \
            printf(__VA_ARGS__);                                            \
            printf("\n");                                                   \
        }                                                                   \
    } while (0)

#define CHECK_EQ_U8(actual, expected)                                       \
    do {                                                                    \
        unsigned _a = (unsigned)(actual);                                   \
        unsigned _e = (unsigned)(expected);                                 \
        g_checks++;                                                         \
        if (_a != _e) {                                                     \
            g_failures++;                                                   \
            printf("FAIL %s:%d: expected 0x%02X got 0x%02X\n",              \
                   __FILE__, __LINE__, _e, _a);                             \
        }                                                                   \
    } while (0)

#define CHECK_EQ_U16(actual, expected)                                      \
    do {                                                                    \
        unsigned _a = (unsigned)(actual);                                   \
        unsigned _e = (unsigned)(expected);                                 \
        g_checks++;                                                         \
        if (_a != _e) {                                                     \
            g_failures++;                                                   \
            printf("FAIL %s:%d: expected 0x%04X got 0x%04X\n",              \
                   __FILE__, __LINE__, _e, _a);                             \
        }                                                                   \
    } while (0)

#define TEST_REPORT()                                                       \
    do {                                                                    \
        printf("%s: %d/%d checks passed\n",                                 \
               g_failures ? "FAILED" : "OK",                                \
               g_checks - g_failures, g_checks);                            \
        return g_failures ? 1 : 0;                                          \
    } while (0)

#endif /* TEST_HARNESS_H */
```

- [ ] **Step 2: 写 `tools/hosttest/test_proto.c` 空壳（Task 4 替换）**

```c
#include "test_harness.h"

int main(void)
{
    printf("placeholder - Task 4 fills in protocol tests\n");
    TEST_REPORT();
}
```

- [ ] **Step 3: 写 `tools/hosttest/run_tests.ps1`**

```powershell
# 宿主侧单元测试（协议编解码器不依赖 HAL，可直接用宿主 gcc 编译）
$ErrorActionPreference = 'Stop'
$repo   = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$here   = $PSScriptRoot
$build  = Join-Path $repo 'build\hosttest'

$gcc = Get-Command gcc -ErrorAction SilentlyContinue
if (-not $gcc) {
    if (Test-Path 'C:\mingw64\bin\gcc.exe') { $gcc = @{ Source = 'C:\mingw64\bin\gcc.exe' } }
    else { throw 'host gcc not found (need MinGW-w64 gcc on PATH)' }
}

New-Item -ItemType Directory -Force -Path $build | Out-Null
$exe = Join-Path $build 'test_proto.exe'

$sources = @(
    (Join-Path $here 'test_proto.c'),
    (Join-Path $repo 'App\Src\tmag_proto.c')
)
$args = @('-std=c11', '-Wall', '-Wextra', '-Werror', '-O1',
          "-I$repo\App\Inc", "-I$here") + $sources + @('-o', $exe)

Write-Output '=== compiling host tests ==='
& $gcc.Source @args
if ($LASTEXITCODE -ne 0) { throw "host test compile failed ($LASTEXITCODE)" }

Write-Output '=== running host tests ==='
& $exe
exit $LASTEXITCODE
```

- [ ] **Step 4: 运行**

Run: `powershell -ExecutionPolicy Bypass -File F:\youko_repo\Tmag3001_for_STM32F4_\tools\hosttest\run_tests.ps1`
Expected: 编译无警告（`-Werror` 生效），输出 `OK: 0/0 checks passed`，退出码 0。

- [ ] **Step 5: 提交**

```
test: 添加宿主侧单元测试基础设施

协议编解码器不依赖 HAL，可用宿主 MinGW-w64 GCC 直接编译测试。
run_tests.ps1 不依赖 make，直接调用 gcc。
```

---

### Task 4: 协议编解码器（固件与 PC 端共享的帧格式）

**Files:**
- Modify: `App/Inc/tmag_proto.h`（替换占位）
- Modify: `App/Src/tmag_proto.c`（替换占位）
- Modify: `tools/hosttest/test_proto.c`（替换占位）

**Interfaces:**
- Consumes: Task 3 的测试基础设施
- Produces:
  - `uint8_t tmag_crc8(const uint8_t *data, size_t len)` — XOR CRC-8
  - `size_t tmag_encode_data(uint8_t *out, uint8_t seq, const tmag_sample_t *s)` — 返回 12
  - `size_t tmag_encode_status(uint8_t *out, uint8_t seq, const tmag_status_t *st)` — 返回 12
  - `size_t tmag_encode_error(uint8_t *out, uint8_t seq, uint8_t err_code, uint8_t i2c_addr, uint8_t reg_addr)` — 返回 12
  - `uint16_t tmag_sensitivity_for_range(uint8_t range_code)` — 0→885, 1→446, 2→273, 3→137
  - 类型 `tmag_sample_t`（4 个 int16 原始值）、`tmag_status_t`（见下）

- [ ] **Step 1: 先写失败的测试 `tools/hosttest/test_proto.c`**

```c
#include "test_harness.h"
#include "tmag_proto.h"

#include <string.h>

/* CRC-8 golden vector: 协议文档 v1.1 §7 示例帧的负载部分 */
static void test_crc8(void)
{
    const uint8_t v[7] = { 0x01, 0x05, 0xD8, 0x00, 0x2C, 0xFF, 0x1E };
    CHECK_EQ_U8(tmag_crc8(v, sizeof(v)), 0xB3);   /* 文档 §7 给出的 CRC */
    CHECK_EQ_U8(tmag_crc8(v, 0), 0x00);
    CHECK_EQ_U8(tmag_crc8((const uint8_t *)"", 0), 0x00);
    CHECK_EQ_U8(tmag_crc8((const uint8_t *)"A", 1), 0x41);
}

static void test_encode_data(void)
{
    uint8_t f[TMAG_PROTO_FRAME_SIZE];
    tmag_sample_t s;
    s.x_raw = 1496;      /* 0x05D8 */
    s.y_raw = 44;        /* 0x002C */
    s.z_raw = -226;      /* 0xFF1E */
    s.temp_raw = 17512;  /* 0x4468 */

    CHECK_EQ_U16(tmag_encode_data(f, 0x01, &s), 12);
    CHECK_EQ_U8(f[0], 0xAA);
    CHECK_EQ_U8(f[1], 0x55);
    CHECK_EQ_U8(f[2], 0x01);
    CHECK_EQ_U8(f[3], 0x05); CHECK_EQ_U8(f[4], 0xD8);
    CHECK_EQ_U8(f[5], 0x00); CHECK_EQ_U8(f[6], 0x2C);
    CHECK_EQ_U8(f[7], 0xFF); CHECK_EQ_U8(f[8], 0x1E);
    CHECK_EQ_U8(f[9], 0x44); CHECK_EQ_U8(f[10], 0x68);
    CHECK_EQ_U8(f[11], tmag_crc8(&f[2], 9));
}

static void test_encode_status(void)
{
    uint8_t f[TMAG_PROTO_FRAME_SIZE];
    tmag_status_t st;
    memset(&st, 0, sizeof(st));
    st.range_code = 0;                       /* ±40 mT */
    st.sensitivity = 885;                    /* 0x0375 */
    st.sample_rate_hz = 100;
    st.err_count = 0;
    st.conv_status = 0x01;                   /* Result_Status = 1 */
    st.device_status = 0x00;
    st.flags = TMAG_FLAG_SENSOR_READY | TMAG_FLAG_CFG_OK | TMAG_FLAG_INT_PATH_OK;

    CHECK_EQ_U16(tmag_encode_status(f, 0x42, &st), 12);
    CHECK_EQ_U8(f[0], 0xAA);
    CHECK_EQ_U8(f[1], 0x56);
    CHECK_EQ_U8(f[2], 0x42);
    CHECK_EQ_U8(f[3], TMAG_PROTO_VERSION);   /* 0x12 */
    CHECK_EQ_U8(f[4], (1u << 2) | (1u << 3) | (1u << 5));  /* 0x2C */
    CHECK_EQ_U8(f[5], 0x03); CHECK_EQ_U8(f[6], 0x75);
    CHECK_EQ_U8(f[7], 100);
    CHECK_EQ_U8(f[8], 0);
    CHECK_EQ_U8(f[9], 0x01);
    CHECK_EQ_U8(f[10], 0x00);
    CHECK_EQ_U8(f[11], tmag_crc8(&f[2], 9));

    /* bit6 CLK_SRC_HSE：置位后应原样出现在 FLAGS 里 */
    st.flags |= TMAG_FLAG_CLK_SRC_HSE;
    tmag_encode_status(f, 0x43, &st);
    CHECK_EQ_U8(f[4], 0x2C | 0x40);
    CHECK_EQ_U8(f[11], tmag_crc8(&f[2], 9));
}

static void test_encode_error(void)
{
    uint8_t f[TMAG_PROTO_FRAME_SIZE];
    CHECK_EQ_U16(tmag_encode_error(f, 0x07, TMAG_ERR_I2C_NACK, 0x34, 0x0E), 12);
    CHECK_EQ_U8(f[0], 0xAA);
    CHECK_EQ_U8(f[1], 0xEE);
    CHECK_EQ_U8(f[2], 0x07);
    CHECK_EQ_U8(f[3], 0x01);
    CHECK_EQ_U8(f[4], 0x34);
    CHECK_EQ_U8(f[5], 0x0E);
    CHECK_EQ_U8(f[6], 0x00); CHECK_EQ_U8(f[7], 0x00);
    CHECK_EQ_U8(f[8], 0x00); CHECK_EQ_U8(f[9], 0x00);
    CHECK_EQ_U8(f[10], 0x00);
    CHECK_EQ_U8(f[11], tmag_crc8(&f[2], 9));
}

static void test_sensitivity_table(void)
{
    CHECK_EQ_U16(tmag_sensitivity_for_range(0), 885);   /* A1 ±40 mT  */
    CHECK_EQ_U16(tmag_sensitivity_for_range(1), 446);   /* A1 ±80 mT  */
    CHECK_EQ_U16(tmag_sensitivity_for_range(2), 273);   /* A2 ±120 mT */
    CHECK_EQ_U16(tmag_sensitivity_for_range(3), 137);   /* A2 ±240 mT */
    CHECK_EQ_U16(tmag_sensitivity_for_range(4), 0);     /* 越界返回 0 */
}

int main(void)
{
    test_crc8();
    test_encode_data();
    test_encode_status();
    test_encode_error();
    test_sensitivity_table();
    TEST_REPORT();
}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `powershell -ExecutionPolicy Bypass -File F:\youko_repo\Tmag3001_for_STM32F4_\tools\hosttest\run_tests.ps1`
Expected: **编译失败**，报错类似 `error: implicit declaration of function 'tmag_crc8'`、`unknown type name 'tmag_sample_t'`。

- [ ] **Step 3: 写实现 `App/Inc/tmag_proto.h`**

```c
/**
 * @file    tmag_proto.h
 * @brief   TMAG3001 串口二进制协议 v1.2 —— 帧格式与编解码
 * @details 纯 C，无 HAL 依赖，可直接在宿主上做单元测试。
 *          协议文档：docs/protocol/TMAG3001_Protocol.md
 */
#ifndef TMAG_PROTO_H
#define TMAG_PROTO_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define TMAG_PROTO_VERSION     0x12
#define TMAG_PROTO_FRAME_SIZE  12
#define TMAG_PROTO_SYNC_BYTE   0xAA

/* ── 帧类型 ── */
typedef enum {
    TMAG_FRAME_DATA   = 0x55,   /* 数据帧 */
    TMAG_FRAME_STATUS = 0x56,   /* 状态帧 */
    TMAG_FRAME_ERROR  = 0xEE    /* 错误帧 */
} tmag_frame_type_t;

/* ── 错误码（固件侧唯一的状态表达）── */
typedef enum {
    TMAG_ERR_NONE        = 0x00, /* 上电初始化成功，传感器就绪 */
    TMAG_ERR_I2C_NACK    = 0x01, /* I2C 总线无应答，传感器未找到 */
    TMAG_ERR_SENSOR_ID   = 0x02, /* 厂商 ID 不匹配（非 TMAG3001） */
    TMAG_ERR_CONFIG_FAIL = 0x03, /* 传感器配置写入失败 */
    TMAG_ERR_I2C_READ    = 0x04, /* 采样期读失败 */
    TMAG_ERR_I2C_TIMEOUT = 0x05, /* I2C 事务超时 */
    TMAG_ERR_NO_CONV     = 0x06, /* 触发后超时未拿到 Result_Status */
    TMAG_ERR_SENSOR_DIAG = 0x07, /* Conv_Status.Diag_Status 置位 */
    TMAG_ERR_OVERFLOW    = 0x08, /* Device_Status 溢出位置位 */
    TMAG_ERR_TX_OVERFLOW = 0x09  /* UART TX 队列溢出（丢帧） */
} tmag_err_code_t;

/* ── 状态帧 FLAGS 位 ── */
#define TMAG_FLAG_RANGE_MASK   0x03  /* bit0-1: 0=±40mT 1=±80mT 2=±120mT 3=±240mT */
#define TMAG_FLAG_SENSOR_READY (1 << 2)
#define TMAG_FLAG_CFG_OK       (1 << 3)
#define TMAG_FLAG_TRIGGER_INT  (1 << 4) /* 1=由 INT 引脚触发转换 */
#define TMAG_FLAG_INT_PATH_OK  (1 << 5) /* 1=EXTI 中断路径实际生效 */
#define TMAG_FLAG_CLK_SRC_HSE  (1 << 6) /* 1=SYSCLK 来自 25MHz 晶振，0=已回退 HSI */

/* ── 数据结构 ── */
typedef struct {
    int16_t x_raw;
    int16_t y_raw;
    int16_t z_raw;
    int16_t temp_raw;
} tmag_sample_t;

typedef struct {
    uint8_t  flags;          /* 位域，bit0-1 由 range_code 填充 */
    uint8_t  range_code;     /* 0=±40mT 1=±80mT 2=±120mT 3=±240mT */
    uint16_t sensitivity;    /* LSB/mT */
    uint8_t  sample_rate_hz;
    uint32_t err_count;
    uint8_t  conv_status;
    uint8_t  device_status;
} tmag_status_t;

/* ── API ── */
uint8_t  tmag_crc8(const uint8_t *data, size_t len);
size_t   tmag_encode_data(uint8_t *out, uint8_t seq, const tmag_sample_t *s);
size_t   tmag_encode_status(uint8_t *out, uint8_t seq, const tmag_status_t *st);
size_t   tmag_encode_error(uint8_t *out, uint8_t seq, uint8_t err_code,
                           uint8_t i2c_addr, uint8_t reg_addr);
uint16_t tmag_sensitivity_for_range(uint8_t range_code);

#ifdef __cplusplus
}
#endif

#endif /* TMAG_PROTO_H */
```

- [ ] **Step 4: 写实现 `App/Src/tmag_proto.c`**

```c
/**
 * @file    tmag_proto.c
 * @brief   TMAG3001 串口二进制协议 v1.2 —— 帧编码实现
 * @note    纯 C，无 HAL 依赖。CRC 覆盖字节 [2..10] 共 9 字节，结果写入 [11]。
 */

#include "tmag_proto.h"

#include <string.h>

/* CRC-8：初值 0x00，逐字节 XOR，无反射无反转（等价多项式 0x07 / MPEG-2） */
uint8_t tmag_crc8(const uint8_t *data, size_t len)
{
    uint8_t crc = 0x00;
    size_t  i;

    if (data == NULL) {
        return crc;
    }
    for (i = 0; i < len; i++) {
        crc ^= data[i];
    }
    return crc;
}

/* 所有帧共用的收尾：填 CRC */
static void tmag_finish(uint8_t *out)
{
    out[11] = tmag_crc8(&out[2], 9);
}

size_t tmag_encode_data(uint8_t *out, uint8_t seq, const tmag_sample_t *s)
{
    if ((out == NULL) || (s == NULL)) {
        return 0;
    }

    out[0] = TMAG_PROTO_SYNC_BYTE;
    out[1] = TMAG_FRAME_DATA;
    out[2] = seq;

    out[3] = (uint8_t)((uint16_t)s->x_raw >> 8);
    out[4] = (uint8_t)(uint16_t)s->x_raw;
    out[5] = (uint8_t)((uint16_t)s->y_raw >> 8);
    out[6] = (uint8_t)(uint16_t)s->y_raw;
    out[7] = (uint8_t)((uint16_t)s->z_raw >> 8);
    out[8] = (uint8_t)(uint16_t)s->z_raw;
    out[9] = (uint8_t)((uint16_t)s->temp_raw >> 8);
    out[10] = (uint8_t)(uint16_t)s->temp_raw;

    tmag_finish(out);
    return TMAG_PROTO_FRAME_SIZE;
}

size_t tmag_encode_status(uint8_t *out, uint8_t seq, const tmag_status_t *st)
{
    uint8_t flags;

    if ((out == NULL) || (st == NULL)) {
        return 0;
    }

    flags = (uint8_t)((st->flags & (uint8_t)~TMAG_FLAG_RANGE_MASK) |
                      (st->range_code & TMAG_FLAG_RANGE_MASK));

    out[0] = TMAG_PROTO_SYNC_BYTE;
    out[1] = TMAG_FRAME_STATUS;
    out[2] = seq;
    out[3] = TMAG_PROTO_VERSION;
    out[4] = flags;
    out[5] = (uint8_t)(st->sensitivity >> 8);
    out[6] = (uint8_t)(uint16_t)st->sensitivity;
    out[7] = st->sample_rate_hz;
    out[8] = (uint8_t)(st->err_count & 0xFF);
    out[9] = st->conv_status;
    out[10] = st->device_status;

    tmag_finish(out);
    return TMAG_PROTO_FRAME_SIZE;
}

size_t tmag_encode_error(uint8_t *out, uint8_t seq, uint8_t err_code,
                          uint8_t i2c_addr, uint8_t reg_addr)
{
    if (out == NULL) {
        return 0;
    }

    out[0] = TMAG_PROTO_SYNC_BYTE;
    out[1] = TMAG_FRAME_ERROR;
    out[2] = seq;
    out[3] = err_code;
    out[4] = i2c_addr;
    out[5] = reg_addr;
    out[6] = 0;
    out[7] = 0;
    out[8] = 0;
    out[9] = 0;
    out[10] = 0;

    tmag_finish(out);
    return TMAG_PROTO_FRAME_SIZE;
}

uint16_t tmag_sensitivity_for_range(uint8_t range_code)
{
    static const uint16_t table[4] = { 885, 446, 273, 137 };

    if (range_code >= 4U) {
        return 0;
    }
    return table[range_code];
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `powershell -ExecutionPolicy Bypass -File F:\youko_repo\Tmag3001_for_STM32F4_\tools\hosttest\run_tests.ps1`
Expected: `OK: 23/23 checks passed`（具体计数以实际断言数为��），退出码 0。

- [ ] **Step 6: 确认固件侧仍能编译**

Run: `powershell -ExecutionPolicy Bypass -File F:\youko_repo\Tmag3001_for_STM32F4_\tools\build.ps1 Release`
Expected: build 成功，产出 `build\Release\TMA3001_.elf`。

- [ ] **Step 7: 提交**

```
feat(proto): 实现 TMAG3001 串口二进制协议 v1.2 编解码

三类帧统一 12 字节：数据帧 0x55 / 状态帧 0x56 / 错误帧 0xEE。
CRC-8 覆盖字节 [2..10]。状态帧下发量程与灵敏度（885/446/273/137），
供 PC 端换算，消除既有 PC 端硬编码 446 LSB/mT 与固件 ±40mT 不一致的缺陷。

纯 C 无 HAL 依赖，宿主单元测试 23 项断言全绿。
```

---

### Task 5: 传感器驱动升级（INT 配置 / 触发 / 批量读）

**Files:**
- Modify: `Drivers/Tmag3001/tmag3001_driver.h`
- Modify: `Drivers/Tmag3001/tmag3001_driver.c`

**Interfaces:**
- Consumes: Task 4 的 `tmag_sensitivity_for_range()`
- Produces:
  - `HAL_StatusTypeDef TMAG3001_ConfigureForAcq(TMAG3001_Handle_t *dev, TMAG3001_Config_t *cfg)` —— 按 datasheet §5.2 写全部寄存器（含 INT 配置）
  - `HAL_StatusTypeDef TMAG3001_TriggerConversion(TMAG3001_Handle_t *dev)` —— 写 `Device_Config_1`（回写当前值）+ A/T=1 触发
  - `HAL_StatusTypeDef TMAG3001_ReadSample(TMAG3001_Handle_t *dev, TMAG3001_Data_t *data)` —— 一次 I2C 事务读 0x10–0x18（9 字节）
  - `TMAG3001_Handle_t` 增加字段 `uint8_t device_config_1;`（缓存回写值，供触发使用）
  - `TMAG3001_Config_t` 增加字段 `TMAG3001_InterruptMode int_mode;` `uint8_t enable_int;`

- [ ] **Step 1: 扩展 `tmag3001_driver.h`**

在 `TMAG3001_Handle_t` 中增加字段：

```c
typedef struct {
    I2C_HandleTypeDef *hi2c;
    uint8_t i2c_addr;
    TMAG3001_MagneticRange range;
    TMAG3001_OperatingMode mode;
    TMAG3001_AveragingMode avg;
    uint8_t device_config_1;   /* 缓存 Device_Config_1 当前值，触发时回写 */
} TMAG3001_Handle_t;
```

在 `TMAG3001_Config_t` 中增加字段：

```c
typedef struct {
    TMAG3001_MagneticRange range;
    TMAG3001_OperatingMode mode;
    TMAG3001_AveragingMode avg;
    TMAG3001_ChannelEnable channels;
    uint8_t enable_int;        /* 1 = 配 INT_Config_1 使能 data-ready 中断 */
} TMAG3001_Config_t;
```

新增寄存器与常量定义（追加到宏区）：

```c
/* 中断相关寄存器（datasheet ZHCSR44C §7.1.8 / §7.1.4） */
#define TMAG3001_REG_INT_CONFIG_1    0x08
#define TMAG3001_REG_SENSOR_CONFIG_2 0x03

/* INT_Config_1 (0x08) 位域 */
#define TMAG3001_INT_RESULT_INT      (1 << 7)  /* 转换完成即中断 */
#define TMAG3001_INT_THRESHOLD_INT   (1 << 6)
#define TMAG3001_INT_LATCHED         (0 << 5)  /* 0=锁存（等控制器寻址清除） */
#define TMAG3001_INT_PULSE           (1 << 5)  /* 1=5us 脉冲 */
#define TMAG3001_INT_MODE_MASK       (0x07 << 2)
#define TMAG3001_INT_MODE_VIA_INT    (1 << 2)  /* INT_Mode=1 经 INT 输出中断 */
#define TMAG3001_INT_POL_EN          (1 << 1)  /* 使能 Sensor_Config_2.INTB_POL */
#define TMAG3001_INT_MASK_INT        (1 << 0)  /* 1=屏蔽 INT 引脚 */

/* Sensor_Config_2 (0x03) 位域 */
#define TMAG3001_T_RATE_FILTER       (1 << 7)  /* 温度按 Conv_AVG 滤波 */
#define TMAG3001_INT_POL_ACTIVE_LOW  (0 << 6)  /* INTB_POL=0：默认高，中断低有效 */
#define TMAG3001_INT_POL_ACTIVE_HIGH (1 << 6)
#define TMAG3001_XY_RANGE_MASK       (1 << 1)
#define TMAG3001_Z_RANGE_MASK        (1 << 0)
```

新增原型：

```c
HAL_StatusTypeDef TMAG3001_ConfigureForAcq(TMAG3001_Handle_t *dev, TMAG3001_Config_t *cfg);
HAL_StatusTypeDef TMAG3001_TriggerConversion(TMAG3001_Handle_t *dev);
HAL_StatusTypeDef TMAG3001_ReadSample(TMAG3001_Handle_t *dev, TMAG3001_Data_t *data);
float            TMAG3001_CountsToTemperature(int16_t counts); /* 已存在，确认签名不变 */
```

- [ ] **Step 2: 在 `tmag3001_driver.c` 中实现三个新函数**

追加到文件末尾：

```c
/* ======================== Acquisition-mode configuration ======================== */

/*
 * 按 datasheet ZHCSR44C §7.1.1–7.1.9 配置采集链：
 *   Device_Config_1 (0x00): CRC_EN=0, Conv_AVG, I2C_RD=0
 *   Device_Config_2 (0x01): Trigger_Mode=0(I2C触发), Operating_Mode=0(待机/触发)
 *   Sensor_Config_1 (0x02): MAG_CH_EN, SLEEPTIME=0
 *   Sensor_Config_2 (0x03): T_Rate=1, INTB_POL=0(低有效), X_Y_Range, Z_Range
 *   INT_Config_1    (0x08): Result_INT=1, INT_State=0(锁存), INT_Mode=1, INT_POL_EN=1
 */
HAL_StatusTypeDef TMAG3001_ConfigureForAcq(TMAG3001_Handle_t *dev, TMAG3001_Config_t *cfg)
{
    uint8_t reg;

    if ((dev == NULL) || (cfg == NULL)) {
        return HAL_ERROR;
    }

    /* Device_Config_1 (0x00): CRC_EN=0 | Conv_AVG[4:2] | I2C_RD[1:0]=0 */
    reg = (uint8_t)(((cfg->avg & 0x07u) << 2) & 0x1Cu);
    dev->device_config_1 = reg;
    if (TMAG3001_WriteRegister(dev, TMAG3001_REG_DEVICE_CONFIG_1, reg) != HAL_OK) {
        return HAL_ERROR;
    }

    /* Device_Config_2 (0x01): THR_HYST=0, LP_LN=0, I2C_Glitch=0, Trigger_Mode=0, Operating_Mode */
    reg = (uint8_t)(cfg->mode & 0x03u);
    if (TMAG3001_WriteRegister(dev, TMAG3001_REG_DEVICE_CONFIG_2, reg) != HAL_OK) {
        return HAL_ERROR;
    }

    /* Sensor_Config_1 (0x02): MAG_CH_EN[7:4] | SLEEPTIME[3:0]=0 */
    reg = (uint8_t)(cfg->channels & 0xF0u);
    if (TMAG3001_WriteRegister(dev, TMAG3001_REG_SENSOR_CONFIG_1, reg) != HAL_OK) {
        return HAL_ERROR;
    }

    /* Sensor_Config_2 (0x03): T_Rate=1 | INTB_POL=0 | X_Y_Range | Z_Range */
    reg = (uint8_t)(TMAG3001_T_RATE_FILTER |
                    (uint8_t)(cfg->range == TMAG3001_RANGE_80mT ? 0x03u : 0x00u));
    if (TMAG3001_WriteRegister(dev, TMAG3001_REG_SENSOR_CONFIG_2, reg) != HAL_OK) {
        return HAL_ERROR;
    }

    /* INT_Config_1 (0x08) */
    if (cfg->enable_int) {
        reg = (uint8_t)(TMAG3001_INT_RESULT_INT |
                        TMAG3001_INT_LATCHED |
                        TMAG3001_INT_MODE_VIA_INT |
                        TMAG3001_INT_POL_EN);
    } else {
        reg = 0x00u;
    }
    if (TMAG3001_WriteRegister(dev, TMAG3001_REG_INT_CONFIG_1, reg) != HAL_OK) {
        return HAL_ERROR;
    }

    dev->range = cfg->range;
    dev->mode  = cfg->mode;
    dev->avg   = cfg->avg;

    return HAL_OK;
}

/*
 * 触发一次转换：向 Device_Config_1 回写当前值，并把控制寄存器的 A/T 位置 1。
 * datasheet §6.5.1.1：向转换触发位写 1 将在寄存器地址解码完成后开始新转换。
 */
HAL_StatusTypeDef TMAG3001_TriggerConversion(TMAG3001_Handle_t *dev)
{
    if (dev == NULL) {
        return HAL_ERROR;
    }
    return TMAG3001_WriteRegister(dev, TMAG3001_REG_DEVICE_CONFIG_1, dev->device_config_1);
}

/*
 * 一次 I2C 事务读取 0x10–0x18 共 9 字节：
 *   T_MS(2) X(2) Y(2) Z(2) Conv_Status(1)
 * 转换结果寄存器在事务开始位被锁定（datasheet §6.5.1），中途完成不会撕裂。
 */
HAL_StatusTypeDef TMAG3001_ReadSample(TMAG3001_Handle_t *dev, TMAG3001_Data_t *data)
{
    uint8_t  buf[9];
    int16_t  temp_raw;

    if ((dev == NULL) || (data == NULL)) {
        return HAL_ERROR;
    }

    if (TMAG3001_ReadMultiple(dev, TMAG3001_REG_T_RESULT_MSB, buf, sizeof(buf)) != HAL_OK) {
        return HAL_ERROR;
    }

    temp_raw = (int16_t)(((uint16_t)buf[0] << 8) | buf[1]);
    data->temp_raw = temp_raw;
    data->x_raw = (int16_t)(((uint16_t)buf[2] << 8) | buf[3]);
    data->y_raw = (int16_t)(((uint16_t)buf[4] << 8) | buf[5]);
    data->z_raw = (int16_t)(((uint16_t)buf[6] << 8) | buf[7]);
    data->conv_status = buf[8];
    data->temperature_C = TMAG3001_CountsToTemperature(temp_raw);

    return HAL_OK;
}
```

- [ ] **Step 3: 扩展 `TMAG3001_Data_t` 以承载原始值**

`TMAG3001_Data_t` 改为：

```c
typedef struct {
    int16_t x_raw;          /* 原始 LSB（供协议帧使用） */
    int16_t y_raw;
    int16_t z_raw;
    int16_t temp_raw;       /* 原始温度计数（协议帧直接用，勿反推） */
    float   x_mT;
    float   y_mT;
    float   z_mT;
    float   temperature_C;
    uint8_t conv_status;
} TMAG3001_Data_t;
```

同时在 `TMAG3001_ReadMagData()` 里补上 `data->x_raw = x_raw; data->y_raw = y_raw; data->z_raw = z_raw;`（在现有 `x_raw/y_raw/z_raw` 局部变量算出之后）。

- [ ] **Step 4: 编译验证**

Run: `powershell -ExecutionPolicy Bypass -File F:\youko_repo\Tmag3001_for_STM32F4_\tools\build.ps1 Release`
Expected: build 成功，无警告。

- [ ] **Step 5: 提交**

```
feat(driver): TMAG3001 驱动支持 data-ready 中断与 I2C 触发转换

按 datasheet ZHCSR44C 实现：
- ConfigureForAcq 写全部采集相关寄存器（含 INT_Config_1：Result_INT=1、
  INT_State=0 锁存、INT_Mode=1、INT_POL_EN=1；Sensor_Config_2：INTB_POL=0 低有效）
- TriggerConversion 回写 Device_Config_1 并置 A/T 位触发转换
- ReadSample 一次 I2C 事务读 0x10–0x18 共 9 字节
- Data_t 增加 x_raw/y_raw/z_raw 原始值字段，供协议帧直接使用
```

---

### Task 6: 固件应用层与 PB5/EXTI5 接入

**Files:**
- Modify: `App/Inc/app.h`（替换占位）
- Modify: `App/Inc/app_config.h`（新建）
- Modify: `App/Src/app.c`（替换占位）
- Modify: `Core/Src/main.c`（重写为薄壳）
- Modify: `Core/Src/stm32f4xx_it.c`（加 `EXTI5_IRQHandler`）
- Modify: `Core/Inc/main.h`（加 `INT1_Pin`）
- Modify: `Core/Src/stm32f4xx_hal_msp.c` 或 `Core/Src/main.c` 的 `MX_GPIO_Init`（配 PB5 EXTI5 + 上拉 + NVIC）

**Interfaces:**
- Consumes: Task 4 的 `tmag_proto.h`、Task 5 的驱动新 API
- Produces:
  - `void App_Init(UART_HandleTypeDef *huart, I2C_HandleTypeDef *hi2c)`
  - `void App_Process(void)` —— 主循环调用
  - `void App_OnSensorInt(void)` —— EXTI 回调
  - `uint8_t App_ClockFromHSE(void)` —— 1=晶振，0=回退内部 RC（在 `main.c` 定义）
  - `app_config.h` 中的 `APP_SAMPLE_RATE_HZ` 宏（Task 8 扫频时改它重编）

- [ ] **Step 1: 写 `App/Inc/app_config.h`**

```c
/**
 * @file    app_config.h
 * @brief   应用层可调常量（单一真相源）
 */
#ifndef APP_CONFIG_H
#define APP_CONFIG_H

/* ── 采样 ──
 * 默认 100 Hz。上限由 P1 扫频实测确定（验收项 A10），
 * 改动此值后重新编译烧录即可做新一轮实测。
 */
#define APP_SAMPLE_RATE_HZ          100U
#define APP_SAMPLE_PERIOD_MS        (1000U / APP_SAMPLE_RATE_HZ)

/* ── 传感器 ── */
#define APP_TMAG_RANGE_CODE         0U    /* 0=±40mT (A1, 885 LSB/mT) */
#define APP_TMAG_I2C_SCAN_FIRST     0x34U
#define APP_TMAG_I2C_SCAN_LAST      0x37U
#define APP_TMAG_I2C_TIMEOUT_MS     20U

/* ── 中断路径 ── */
#define APP_INT_TIMEOUT_MS          5U    /* 触发后等待 EXTI 的超时 */

/* ── 状态心跳 ── */
#define APP_STATUS_PERIOD_MS        1000U

/* ── UART ── */
#define APP_UART_BAUD               115200U

#endif /* APP_CONFIG_H */
```

- [ ] **Step 2: 写 `App/Inc/app.h`**

```c
/**
 * @file    app.h
 * @brief   应用层接口：初始化、采样状态机、传感器中断回调
 */
#ifndef APP_H
#define APP_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* 应用状态 */
typedef enum {
    APP_STATE_INIT = 0,   /* 初始化中 */
    APP_STATE_READY,      /* 传感器就绪，正在采集 */
    APP_STATE_DEGRADED,   /* 传感器故障，降级重试 */
    APP_STATE_FATAL       /* 不可恢复 */
} app_state_t;

/* 初始化：传入外设句柄，内部完成传感器扫描/配置并发出首个状态帧 */
void App_Init(UART_HandleTypeDef *huart, I2C_HandleTypeDef *hi2c);

/* 主循环调用：推进采样状态机、发送帧 */
void App_Process(void);

/* EXTI5 (PB5) 下降沿回调：只置标志，不在中断里做 I2C */
void App_OnSensorInt(void);

/* 时钟源查询：1=SYSCLK 来自 25MHz 晶振，0=已回退内部 RC（在 main.c 里定义） */
uint8_t App_ClockFromHSE(void);

#ifdef __cplusplus
}
#endif

#endif /* APP_H */
```

- [ ] **Step 3: 写 `App/Src/app.c`**

```c
/**
 * @file    app.c
 * @brief   TMAG3001 采集应用层
 *
 * 采样闭环：
 *   主循环 → 距上次触发 ≥ APP_SAMPLE_PERIOD_MS → I2C 触发转换
 *         → 传感器转换完成 → INT 拉低 → EXTI5 下降沿 → App_OnSensorInt 置标志
 *         → 主循环读到标志 → 一次 I2C 事务读 9 字节 → 编码数据帧 → UART DMA 发送
 *
 * 兜底：若 APP_INT_TIMEOUT_MS 内没等到 EXTI，则轮询 Conv_Status；
 *       仍无 Result_Status 则发 ERR_NO_CONV，并在状态帧里清 INT_PATH_OK。
 */

#include "app.h"
#include "app_config.h"
#include "tmag_proto.h"
#include "tmag3001_driver.h"

#include <string.h>

/* ── 私有状态 ── */
static UART_HandleTypeDef *s_huart = NULL;
static I2C_HandleTypeDef  *s_hi2c = NULL;

static TMAG3001_Handle_t  s_sensor;
static TMAG3001_Data_t    s_sample;

static app_state_t s_state       = APP_STATE_INIT;
static uint8_t     s_seq         = 0;
static uint8_t     s_flags       = 0;
static uint8_t     s_range_code  = APP_TMAG_RANGE_CODE;
static uint16_t    s_sensitivity = 0;
static uint32_t    s_err_count   = 0;
static uint8_t     s_conv_status = 0;
static uint8_t     s_device_status = 0;

static volatile uint8_t s_int_pending = 0;
static uint32_t s_last_trigger_ms = 0;
static uint32_t s_last_status_ms  = 0;
static uint32_t s_int_ok_count    = 0;
static uint32_t s_int_miss_count  = 0;

/* ── UART 发送环形缓冲（16 帧）── */
#define APP_TX_RING_FRAMES 16
static uint8_t  s_tx_ring[APP_TX_RING_FRAMES][TMAG_PROTO_FRAME_SIZE];
static volatile uint16_t s_tx_head = 0;   /* 生产者：主循环 */
static volatile uint16_t s_tx_tail = 0;   /* 消费者：DMA 完成回调 */

static uint32_t s_tick_ms(void)
{
    return HAL_GetTick();
}

static uint32_t s_elapsed(uint32_t since)
{
    return (uint32_t)(s_tick_ms() - since);
}

/* ── UART DMA 发送 ── */

static int app_tx_push(const uint8_t *frame)
{
    uint16_t next = (uint16_t)((s_tx_head + 1u) % APP_TX_RING_FRAMES);

    if (next == s_tx_tail) {
        /* 环满 → 记一次 TX 溢出 */
        s_err_count++;
        return -1;
    }
    memcpy(s_tx_ring[s_tx_head], frame, TMAG_PROTO_FRAME_SIZE);
    s_tx_head = next;

    /* 若 DMA 空闲则启动一次传输 */
    if (HAL_UART_GetState(s_huart) == HAL_UART_STATE_READY) {
        uint16_t tail = s_tx_tail;
        HAL_UART_Transmit_DMA(s_huart, s_tx_ring[tail], TMAG_PROTO_FRAME_SIZE);
    }
    return 0;
}

void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART1) {
        s_tx_tail = (uint16_t)((s_tx_tail + 1u) % APP_TX_RING_FRAMES);
        if (s_tx_head != s_tx_tail) {
            HAL_UART_Transmit_DMA(s_huart, s_tx_ring[s_tx_tail], TMAG_PROTO_FRAME_SIZE);
        }
    }
}

/* ── 传感器初始化 ── */

static HAL_StatusTypeDef app_scan_i2c(uint8_t *found_addr)
{
    uint8_t addr;

    for (addr = APP_TMAG_I2C_SCAN_FIRST; addr <= APP_TMAG_I2C_SCAN_LAST; addr++) {
        if (HAL_I2C_IsDeviceReady(s_hi2c, (uint16_t)(addr << 1), 2,
                                  APP_TMAG_I2C_TIMEOUT_MS) == HAL_OK) {
            *found_addr = addr;
            return HAL_OK;
        }
    }
    return HAL_ERROR;
}

static void app_send_error(uint8_t code, uint8_t i2c_addr, uint8_t reg_addr)
{
    uint8_t frame[TMAG_PROTO_FRAME_SIZE];

    if (tmag_encode_error(frame, s_seq++, code, i2c_addr, reg_addr) == TMAG_PROTO_FRAME_SIZE) {
        (void)app_tx_push(frame);
    }
}

static void app_send_status(void)
{
    uint8_t frame[TMAG_PROTO_FRAME_SIZE];
    tmag_status_t st;

    memset(&st, 0, sizeof(st));
    st.flags          = s_flags;
    st.range_code     = s_range_code;
    st.sensitivity    = s_sensitivity;
    st.sample_rate_hz = (uint8_t)APP_SAMPLE_RATE_HZ;
    st.err_count      = s_err_count;
    st.conv_status    = s_conv_status;
    st.device_status  = s_device_status;

    if (tmag_encode_status(frame, s_seq++, &st) == TMAG_PROTO_FRAME_SIZE) {
        (void)app_tx_push(frame);
    }
    s_last_status_ms = s_tick_ms();
}

/* ── 初始化 ── */

void App_Init(UART_HandleTypeDef *huart, I2C_HandleTypeDef *hi2c)
{
    uint8_t addr = 0;
    HAL_StatusTypeDef st;
    TMAG3001_Config_t cfg;

    s_huart = huart;
    s_hi2c = hi2c;

    memset(&cfg, 0, sizeof(cfg));
    cfg.range     = TMAG3001_RANGE_40mT;
    cfg.mode      = TMAG3001_MODE_STANDBY;   /* Operating_Mode=0 待机/触发 */
    cfg.avg       = TMAG3001_AVG_1X;         /* Conv_AVG=0 */
    cfg.channels  = TMAG3001_CH_XYZ;         /* MAG_CH_EN=0x70 */
    cfg.enable_int = 1;                      /* 使能 data-ready 中断 */

    s_range_code  = APP_TMAG_RANGE_CODE;
    s_sensitivity = tmag_sensitivity_for_range(s_range_code);

    /* 扫描 I2C 地址 */
    if (app_scan_i2c(&addr) != HAL_OK) {
        s_state = APP_STATE_DEGRADED;
        s_flags = 0;
        app_send_error(TMAG_ERR_I2C_NACK, 0x00, 0x00);
        app_send_status();
        return;
    }

    s_sensor.hi2c      = s_hi2c;
    s_sensor.i2c_addr  = addr;
    s_sensor.range     = cfg.range;
    s_sensor.mode      = cfg.mode;
    s_sensor.avg       = cfg.avg;
    s_sensor.device_config_1 = 0x00;

    st = TMAG3001_Init(&s_sensor, s_hi2c);
    if (st != HAL_OK) {
        s_state = APP_STATE_DEGRADED;
        app_send_error(TMAG_ERR_SENSOR_ID, addr, TMAG3001_REG_MANUF_ID_LSB);
        app_send_status();
        return;
    }

    st = TMAG3001_ConfigureForAcq(&s_sensor, &cfg);
    if (st != HAL_OK) {
        s_state = APP_STATE_DEGRADED;
        app_send_error(TMAG_ERR_CONFIG_FAIL, addr, TMAG3001_REG_DEVICE_CONFIG_1);
        app_send_status();
        return;
    }

    s_state = APP_STATE_READY;
    s_flags = TMAG_FLAG_SENSOR_READY | TMAG_FLAG_CFG_OK | TMAG_FLAG_INT_PATH_OK;
    if (App_ClockFromHSE()) {
        s_flags |= TMAG_FLAG_CLK_SRC_HSE;   /* 1=晶振，0=已回退内部 RC */
    }

    app_send_error(TMAG_ERR_NONE, addr, 0x00);   /* 就绪信号 */
    app_send_status();

    s_last_trigger_ms = s_tick_ms();
    s_last_status_ms  = s_tick_ms();
}

/* ── EXTI 回调 ── */

void App_OnSensorInt(void)
{
    s_int_pending = 1;
}

/* HAL_GPIO_EXTI_Callback 在这里重实现（HAL 里的版本是 weak） */
void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin)
{
    if (GPIO_Pin == GPIO_PIN_5) {
        App_OnSensorInt();
    }
}

/* ── 主循环 ── */

static void app_handle_sample(void)
{
    uint8_t frame[TMAG_PROTO_FRAME_SIZE];
    tmag_sample_t ts;

    if (TMAG3001_ReadSample(&s_sensor, &s_sample) != HAL_OK) {
        s_err_count++;
        app_send_error(TMAG_ERR_I2C_READ, s_sensor.i2c_addr, TMAG3001_REG_T_RESULT_MSB);
        return;
    }

    s_conv_status = s_sample.conv_status;

    if ((s_conv_status & 0x01u) == 0u) {
        /* Result_Status 未就绪 */
        s_err_count++;
        app_send_error(TMAG_ERR_NO_CONV, s_sensor.i2c_addr, TMAG3001_REG_CONV_STATUS);
        return;
    }

    if ((s_conv_status & 0x02u) != 0u) {
        /* Diag_Status 置位 */
        s_err_count++;
        app_send_error(TMAG_ERR_SENSOR_DIAG, s_sensor.i2c_addr, TMAG3001_REG_CONV_STATUS);
    }

    ts.x_raw     = s_sample.x_raw;
    ts.y_raw     = s_sample.y_raw;
    ts.z_raw     = s_sample.z_raw;
    ts.temp_raw  = s_sample.temp_raw;

    if (tmag_encode_data(frame, s_seq++, &ts) == TMAG_PROTO_FRAME_SIZE) {
        if (app_tx_push(frame) != 0) {
            app_send_error(TMAG_ERR_TX_OVERFLOW, 0x00, 0x00);
        }
    }
}

void App_Process(void)
{
    if (s_state != APP_STATE_READY) {
        /* 降级态：每秒重试一次初始化 */
        if (s_elapsed(s_last_status_ms) >= APP_STATUS_PERIOD_MS) {
            App_Init(s_huart, s_hi2c);
        }
        return;
    }

    if (s_int_pending) {
        s_int_pending = 0;
        s_int_ok_count++;
        app_handle_sample();
        s_last_trigger_ms = s_tick_ms();
        return;
    }

    /* 已触发但没等到 EXTI → 超时兜底 */
    if ((s_elapsed(s_last_trigger_ms) >= APP_INT_TIMEOUT_MS) &&
        (s_elapsed(s_last_trigger_ms) < APP_SAMPLE_PERIOD_MS)) {
        s_int_miss_count++;
        s_flags &= (uint8_t)~TMAG_FLAG_INT_PATH_OK;
        s_err_count++;
        app_send_error(TMAG_ERR_NO_CONV, s_sensor.i2c_addr, TMAG3001_REG_CONV_STATUS);
        s_last_trigger_ms = s_tick_ms();
    } else if (s_elapsed(s_last_trigger_ms) >= APP_SAMPLE_PERIOD_MS) {
        /* 到点：触发下一次转换 */
        if (TMAG3001_TriggerConversion(&s_sensor) != HAL_OK) {
            s_err_count++;
            app_send_error(TMAG_ERR_I2C_READ, s_sensor.i2c_addr, TMAG3001_REG_DEVICE_CONFIG_1);
        }
        s_last_trigger_ms = s_tick_ms();
    }

    if (s_elapsed(s_last_status_ms) >= APP_STATUS_PERIOD_MS) {
        app_send_status();
    }
}
```

> **温度原始值**：`ts.temp_raw` 直接取自 `s_sample.temp_raw`，该字段由 `TMAG3001_ReadSample()`（Task 5）在同一次 I2C 事务中读出并保留原始计数，**不做任何反推换算**（由摄氏温度反推会损失精度）。

- [ ] **Step 4: 重写 `Core/Src/main.c` 为薄壳**

**先改时钟树（关键，见 spec §5.1.1）**：遗产固件虽然跑 96 MHz，却用的是内部 RC（HSI），**完全没用板上的 25 MHz 晶振**；而 `.ioc` 一边声明 `RCC.HSE_VALUE=25000000` 与 PH0/PH1 为 HSE 引脚，一边配着按 HSI 推的 `PLLM=8`（25/8 = 3.125 MHz 非整数，HSE 下 PLL 锁不上）。

把 `SystemClock_Config()` 换成下面这版 —— **HSE 优先，起振失败自动回退 HSI，两条路径都是 96 MHz**：

```c
/* 时钟：HSE 25 MHz 晶振(PH0/PH1) → 96 MHz；HSE 起振失败回退 HSI(同为 96 MHz)
 *   HSE 路径：25/PLLM(25)=1MHz VCO in → PLLN(192)=192MHz VCO out
 *             → PLLP(2)=96MHz SYSCLK，PLLQ(4)=48MHz
 *   HSI 路径：16/PLLM(8)=2MHz VCO in → PLLN(96)=192MHz VCO out
 *             → PLLP(2)=96MHz SYSCLK，PLLQ(4)=48MHz
 * 注意：F411 的 HSE 没有预分频器，RCC_OscInitTypeDef 在 F411 上没有
 *       HSEPredivValue 字段（F42x/43x 才有），写它会编译失败。
 */
static uint8_t s_clk_from_hse = 0;

uint8_t App_ClockFromHSE(void)
{
    return s_clk_from_hse;
}

void SystemClock_Config(void)
{
    RCC_OscInitTypeDef RCC_OscInitStruct = {0};
    RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

    __HAL_RCC_PWR_CLK_ENABLE();
    __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

    RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK |
                                  RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
    RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
    RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;   /* PCLK1 = 48 MHz */
    RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;   /* PCLK2 = 96 MHz */

    /* ① 优先用 25 MHz 晶振 */
    RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
    RCC_OscInitStruct.HSEState = RCC_HSE_ON;
    RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
    RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
    RCC_OscInitStruct.PLL.PLLM = 25;
    RCC_OscInitStruct.PLL.PLLN = 192;
    RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
    RCC_OscInitStruct.PLL.PLLQ = 4;

    if ((HAL_RCC_OscConfig(&RCC_OscInitStruct) == HAL_OK) &&
        (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_3) == HAL_OK)) {
        s_clk_from_hse = 1;
        return;
    }

    /* ② 晶振没起振 → 回退内部 RC（同样 96 MHz，只是精度差） */
    RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
    RCC_OscInitStruct.HSEState = RCC_HSE_OFF;
    RCC_OscInitStruct.HSIState = RCC_HSI_ON;
    RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
    RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
    RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;
    RCC_OscInitStruct.PLL.PLLM = 8;
    RCC_OscInitStruct.PLL.PLLN = 96;
    RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
    RCC_OscInitStruct.PLL.PLLQ = 4;

    if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK) {
        Error_Handler();
    }
    if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_3) != HAL_OK) {
        Error_Handler();
    }
    s_clk_from_hse = 0;
}
```

**同步修正 `.ioc` 的 RCC 标量**（`.ioc` 只作参考、不跑 Generate Code，但要让将来的再生成得到同样结果）：
`RCC.PLLM=8` → `25`；`RCC.PLLN=96` → `192`；`RCC.VCOInputFreq_Value=2000000` → `1000000`；
并补 `RCC.PLLSource=RCC_PLLSOURCE_HSE`（若该键不存在）。
改完用 CubeIDE 1.19.0（`C:\ST\STM32CubeIDE_1.19.0`）的 CubeMX 打开确认能正常加载。

**再把主函数瘦身为**：

```c
/* USER CODE BEGIN Includes */
#include "tmag3001_driver.h"
#include "app.h"
/* USER CODE END Includes */

/* ... 保留原有的 I2C_HandleTypeDef hi2c1; UART_HandleTypeDef huart1;
        DMA/TIM 句柄（TIM2 本方案不用，可删）... */

/* USER CODE BEGIN 2 */
  App_Init(&huart1, &hi2c1);
/* USER CODE END 2 */

  /* Infinite loop */
  while (1)
  {
    App_Process();
  }
```

具体改动：
1. 删除 `LCD_ShowBootScreen()` / `LCD_ShowMagData()` 及其调用（板上不做 UI）。
2. 删除 `USART1_SendString()` 与所有 `snprintf` 文本输出（固件只发二进制帧）。
3. 删除 `MX_SPI1_Init()` 的调用与 `hspi1` 句柄（不接屏幕）。
4. 删除 `MX_TIM2_Init()` 的调用与 `htim2`（采样由传感器 INT 驱动，不再需要定时器触发）。
5. `HAL_TIM_PeriodElapsedCallback()` 可删除。
6. `MX_GPIO_Init()` 中新增 PB5 的 EXTI 配置与 NVIC 使能。
7. `MX_DMA_Init()` 保留 USART1 的 DMA2_Stream2/7 使能。

`MX_GPIO_Init()` 中新增的 PB5 配置（插入到 `MX_GPIO_Init` 里，`GPIO Ports Clock Enable` 之后）：

```c
  /*Configure GPIO pin : INT1_Pin (PB5) —— TMAG3001 data-ready，开漏输出+外部10k上拉 */
  GPIO_InitStruct.Pin = INT1_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_IT_FALLING;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(INT1_GPIO_Port, &GPIO_InitStruct);

  /* EXTI interrupt init for EXTI5 */
  HAL_NVIC_SetPriority(EXTI5_IRQn, 2, 0);
  HAL_NVIC_EnableIRQ(EXTI5_IRQn);
```

`Core/Inc/main.h` 中新增：

```c
#define INT1_Pin                 GPIO_PIN_5
#define INT1_GPIO_Port           GPIOB
```

- [ ] **Step 5: 在 `Core/Src/stm32f4xx_it.c` 中新增 EXTI5 处理**

```c
/**
  * @brief This function handles EXTI line[5] interrupts.
  */
void EXTI5_IRQHandler(void)
{
  /* USER CODE BEGIN EXTI5_IRQn 0 */

  /* USER CODE END EXTI5_IRQn 0 */
  HAL_GPIO_EXTI_IRQHandler(INT1_Pin);
  /* USER CODE BEGIN EXTI5_IRQn 1 */

  /* USER CODE END EXTI5_IRQn 1 */
}
```

同时确认 `Core/Src/stm32f4xx_it.c` 顶部已 `#include "main.h"`。

- [ ] **Step 6: 编译验证**

Run: `powershell -ExecutionPolicy Bypass -File F:\youko_repo\Tmag3001_for_STM32F4_\tools\build.ps1 Release`
Expected: build 成功。`arm-none-eabi-size` 输出的 text 应显著小于 Task 2 的 129976（因为 ST7789 与 fonts 不再参与构建）。

- [ ] **Step 7: 提交**

```
feat(app): 应用层采样状态机与 PB5/EXTI5 数据就绪中断

- App/ 分为 app.h/app_config.h/app.c：初始化、采样状态机、EXTI 回调、帧调度
- main.c 瘦身为薄壳，删除全部 LCD/ST7789/TIM2/文本输出
- PB5 配 EXTI5 下降沿 + 内部上拉 + NVIC 使能；EXTI5_IRQHandler 已接
- UART DMA 16 帧环形缓冲，溢出记 ERR_TX_OVERFLOW
- 触发后 APP_INT_TIMEOUT_MS 内无 EXTI 则发 ERR_NO_CONV 并清 INT_PATH_OK 位
```

---

### Task 7: 烧录与探测脚本 + 首次实机验证

**Files:**
- Create: `tools/flash.ps1`
- Create: `tools/probe.ps1`
- Create: `tools/hosttest/test_capture.py`

**Interfaces:**
- Consumes: Task 6 的固件
- Produces: 一键烧录能力；`test_capture.py` 能解帧并统计（PC 端协议实现的基础设施，Task B 会复用其解析逻辑）

- [ ] **Step 1: 写 `tools/flash.ps1`**

```powershell
# 烧录 + 校验 + 复位：STM32CubeProgrammer CLI（CubeCLT 自带）
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$preset = if ($args.Count -ge 1) { $args[0] } else { 'Release' }

$cli = 'C:\ST\STM32CubeCLT_1.21.0\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe'
if (-not (Test-Path $cli)) { throw "STM32_Programmer_CLI not found: $cli" }

$elf = Join-Path $repo "build\$preset\TMA3001_.elf"
if (-not (Test-Path $elf)) { throw "elf not found: $elf (run tools/build.ps1 first)" }

Write-Output "=== flashing $elf ==="
& $cli -c port=SWD -w $elf -v -rst
if ($LASTEXITCODE -ne 0) { throw "flash failed ($LASTEXITCODE)" }
Write-Output '=== flash OK ==='
```

- [ ] **Step 2: 写 `tools/probe.ps1`**

```powershell
# 读取芯片信息 / 复位
$ErrorActionPreference = 'Stop'
$cli = 'C:\ST\STM32CubeCLT_1.21.0\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe'
if (-not (Test-Path $cli)) { throw "STM32_Programmer_CLI not found: $cli" }

$mode = if ($args.Count -ge 1) { $args[0] } else { 'info' }

switch ($mode) {
    'info' {
        & $cli -c port=SWD mode=HOTPLUG -r32 0xE000ED00 1
    }
    'reset' {
        & $cli -c port=SWD -rst
    }
    default { throw "unknown mode: $mode (use info|reset)" }
}
if ($LASTEXITCODE -ne 0) { throw "probe failed ($LASTEXITCODE)" }
```

- [ ] **Step 3: 写 `tools/hosttest/test_capture.py`**

```python
"""串口抓包与帧解码工具。

用法:
    python tools/hosttest/test_capture.py --port COM9 --seconds 10 [--rate 100]

输出: 每秒一行统计 + 前 20 帧明细。
"""
from __future__ import annotations

import argparse
import collections
import struct
import sys
import time

FRAME_SIZE = 12
SYNC = 0xAA
TYPE_DATA = 0x55
TYPE_STATUS = 0x56
TYPE_ERROR = 0xEE

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


def crc8(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
    return crc


def parse_frame(frame: bytes):
    if len(frame) != FRAME_SIZE or frame[0] != SYNC:
        return None
    if frame[1] not in (TYPE_DATA, TYPE_STATUS, TYPE_ERROR):
        return None
    if crc8(frame[2:11]) != frame[11]:
        return None
    seq = frame[2]
    if frame[1] == TYPE_DATA:
        x, y, z, t = struct.unpack(">hhhh", frame[3:11])
        return ("data", seq, x, y, z, t)
    if frame[1] == TYPE_STATUS:
        ver, flags, sens_h, sens_l, rate, errcnt, conv, devst = struct.unpack(
            ">BBHBBBB", frame[3:11]
        )
        return ("status", seq, ver, flags, (sens_h << 8) | sens_l, rate, errcnt, conv, devst)
    code = frame[3]
    return ("error", seq, code, ERR_NAMES.get(code, f"UNKNOWN_0x{code:02X}"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM9")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--seconds", type=float, default=10.0)
    args = ap.parse_args()

    try:
        import serial
    except ImportError:
        print("pyserial not installed: pip install pyserial", file=sys.stderr)
        return 2

    ser = serial.Serial(args.port, args.baud, timeout=0.2)
    buf = bytearray()
    counts = collections.Counter()
    shown = 0
    last_seq = None
    dropped = 0
    start = time.time()
    last_report = start

    try:
        while time.time() - start < args.seconds:
            chunk = ser.read(ser.in_waiting or 1)
            if chunk:
                buf.extend(chunk)
            while len(buf) >= FRAME_SIZE:
                idx = buf.find(b"\xAA")
                if idx < 0:
                    buf.clear()
                    break
                if idx:
                    del buf[:idx]
                if len(buf) < FRAME_SIZE:
                    break
                parsed = parse_frame(bytes(buf[:FRAME_SIZE]))
                if parsed is None:
                    del buf[0]
                    continue
                del buf[:FRAME_SIZE]
                counts[parsed[0]] += 1
                if parsed[0] == "data":
                    if last_seq is not None:
                        expected = (last_seq + 1) & 0xFF
                        if parsed[1] != expected:
                            dropped += (parsed[1] - expected) & 0xFF
                    last_seq = parsed[1]
                    if shown < 20:
                        print(
                            f"[seq {parsed[1]:3d}] x={parsed[2]:6d} y={parsed[3]:6d} "
                            f"z={parsed[4]:6d} t_raw={parsed[5]:6d}"
                        )
                        shown += 1
                elif parsed[0] == "status":
                    if shown < 20:
                        print(
                            f"[status seq {parsed[1]:3d}] ver=0x{parsed[2]:02X} "
                            f"flags=0x{parsed[3]:02X} sens={parsed[4]} "
                            f"rate={parsed[5]}Hz errcnt={parsed[6]} "
                            f"conv=0x{parsed[7]:02X} dev=0x{parsed[8]:02X}"
                        )
                        shown += 1
                elif parsed[0] == "error":
                    print(f"[error seq {parsed[1]:3d}] {parsed[3]}")
            now = time.time()
            if now - last_report >= 1.0:
                total = sum(counts.values())
                print(
                    f"--- {now - start:5.1f}s  data={counts['data']} status={counts['status']} "
                    f"error={counts['error']} total={total} "
                    f"rate={total / max(now - start, 1e-9):.1f}/s dropped={dropped}"
                )
                last_report = now
    finally:
        ser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 烧录**

Run: `powershell -ExecutionPolicy Bypass -File F:\youko_repo\Tmag3001_for_STM32F4_\tools\flash.ps1 Release`
Expected: 输出 `Device name: STM32F411xC/E`、`Download verified successfully`、退出码 0。

- [ ] **Step 5: 抓包验证状态帧**

Run: `C:\ProgramData\Anaconda3\python.exe F:\youko_repo\Tmag3001_for_STM32F4_\tools\hosttest\test_capture.py --port COM9 --seconds 5`
Expected（**传感器未接时**）：
- 出现 `[error ...] I2C_NACK` 行
- 出现 `[status ...]` 行，其中 `flags` 的 bit2（SENSOR_READY）应为 0
- 每秒统计行出现，`data=0`

Expected（**传感器已接时**）：
- 出现 `[status ...] flags=0x2C`（bit2|bit3|bit5）或类似含 READY+CFG_OK+INT_PATH_OK 的值
- `data=N` 持续增长，`dropped=0`
- `rate=` 接近 100

- [ ] **Step 6: 提交**

```
feat(tools): 烧录/探测脚本与串口抓包解码工具

tools/flash.ps1：STM32CubeProgrammer CLI 一键烧录+校验+复位
tools/probe.ps1：读芯片信息 / 复位
tools/hosttest/test_capture.py：12 字节帧解码 + 丢帧统计 + 速率统计
```

---

### Task 8: 采样率扫频与上限确定

**Files:**
- Modify: `App/Inc/app_config.h`（反复改 `APP_SAMPLE_RATE_HZ`）
- Create: `docs/superpowers/plans/2026-11-07-sample-rate-sweep-results.md`（实测结论）

**Interfaces:**
- Consumes: Task 7 的烧录与抓包工具
- Produces: 各采样率档位的实测数据表 + 确定的默认工作点；写入 `docs/protocol/TMAG3001_Protocol.md` 的"帧率"章节

- [ ] **Step 1: 逐档扫频**

对 `APP_SAMPLE_RATE_HZ` 取 `100 / 200 / 500 / 1000`，每次：

```powershell
# 1) 改 App/Inc/app_config.h 里的 APP_SAMPLE_RATE_HZ
# 2) 重编 + 烧录
powershell -ExecutionPolicy Bypass -File tools\build.ps1 Release
powershell -ExecutionPolicy Bypass -File tools\flash.ps1 Release
# 3) 抓 20 秒
C:\ProgramData\Anaconda3\python.exe tools\hosttest\test_capture.py --port COM9 --seconds 20
```

记录每档的：`rate=`（实际帧/秒）、`dropped=`、`error=` 计数、状态帧里的 `errcnt`。

- [ ] **Step 2: 定位瓶颈**

判读规则：

| 现象 | 瓶颈 | 结论 |
|---|---|---|
| `rate` 远低于设定值，`dropped` 为 0，`errcnt` 为 0 | MCU 主循环 / I2C 事务耗时 | I2C 是瓶颈 |
| `rate` 接近设定值但 `dropped` > 0 | UART 背压（TX 环溢出） | UART 是瓶颈 |
| `errcnt` 持续增长，`error` 帧多为 `NO_CONV` | 传感器转换/中断路径 | INT 路径有问题 |
| `rate` 稳定且 `dropped=0`、`errcnt=0` | — | 该档位已达上限 |

- [ ] **Step 3: 抬高总线速率再测（若 100 kHz/115200 是瓶颈）**

分别尝试：
- I2C1 改 400 kHz（`hi2c1.Init.ClockSpeed = 400000;`）
- UART 改 921600（`huart1.Init.BaudRate = 921600;`）

器件侧支持最高 1 MHz I2C（datasheet §6.5.1.1），MCU 侧无障碍。改动后重跑 Step 1。

- [ ] **Step 4: 写结论文档**

`docs/superpowers/plans/2026-11-07-sample-rate-sweep-results.md` 内容格式：

```markdown
# 采样率实测结果（2026-11-07）

| 目标速率 | I2C | UART | 实测帧率 | 丢帧 | errcnt | 瓶颈判定 |
|---|---|---|---|---|---|---|
| 100 Hz | 100k | 115200 |  |  |  |  |
| 200 Hz | 100k | 115200 |  |  |  |  |
| 500 Hz | 100k | 115200 |  |  |  |  |
| 1000 Hz | 100k | 115200 |  |  |  |  |

**结论**：默认工作点 = ____ Hz；推荐上限 = ____ Hz。
**建议配置**：I2C ____ / UART ____。
```

- [ ] **Step 5: 把最终默认速率写回 `App/Inc/app_config.h`**

若实测显示默认 100 Hz 不是最优，把 `APP_SAMPLE_RATE_HZ` 改成实测结论值（**保持默认不激进**：选稳定零丢帧的档位）。

- [ ] **Step 6: 提交**

```
perf(sweep): 采样率扫频实测并确定默认工作点

各档实测数据见 docs/superpowers/plans/2026-11-07-sample-rate-sweep-results.md。
瓶颈定位与总线速率建议已写入协议文档。
```

---

### Task 9: 协议文档与 README

**Files:**
- Create: `docs/protocol/TMAG3001_Protocol.md`
- Create: `README.md`
- Modify: `docs/superpowers/specs/2026-11-07-tmag3001-f411-pipeline-design.md`（§5.3.1 补实测结论）

**Interfaces:**
- Consumes: Task 4 的协议实现、Task 8 的扫频结论
- Produces: 面向人（开发者/agent）的协议与使用说明；PC 端实现 Task B 的唯一依据

- [ ] **Step 1: 写 `docs/protocol/TMAG3001_Protocol.md`**

必须包含（逐节）：

1. **物理层**：USART1 @115200 8N1，无流控，DMA 发送；ST-Link VCP → COM9。
2. **帧格式总览**：三类帧统一 12 字节；字节表（索引 / 字段 / 说明）。
3. **数据帧 TYPE=0x55**：字段定义 + 大端 int16 + 灵敏度换算公式（`mT = raw / sensitivity`，sensitivity 由状态帧给出）。
4. **状态帧 TYPE=0x56**：逐位说明 FLAGS（bit0-1 RANGE / bit2 SENSOR_READY / bit3 CFG_OK / bit4 TRIGGER_INT / bit5 INT_PATH_OK）、SENS、RATE、ERRCNT、CONV_STATUS、DEVICE_STATUS。
5. **错误帧 TYPE=0xEE**：错误码表（0x00–0x09，逐个写宏名、触发条件、后果）。
6. **CRC-8**：算法、覆盖范围 `[2..10]`、golden vector（`01 05 D8 00 2C FF 1E` → `0xB3`）。
7. **量程与灵敏度对照表**：885 / 446 / 273 / 137。
8. **解析流程**：扫同步头 → 判 TYPE → 校验 CRC → 分发 → SEQ 检丢帧。
9. **Python 解码参考实现**：与 `tools/hosttest/test_capture.py` 一致。
10. **帧率**：填入 Task 8 的实测结论。
11. **修订历史**：1.0 / 1.1（历史，F407 时代）/ **1.2（当前）**。

- [ ] **Step 2: 写 `README.md`**

必须包含：

1. **项目简介**：STM32F411CEU6 + TMAG3001A1 三轴磁力计采集器；固件发二进制帧，PC 端可视化。
2. **目录结构**。
3. **环境要求**：CMake ≥3.22、Ninja、arm-none-eabi-gcc（CubeCLT 1.21.0 已装）、STM32CubeProgrammer、STM32Cube_FW_F4 V1.28.3；宿主测试需 MinGW-w64 gcc。
4. **构建**：`tools\build.ps1 Release`；或手工 `cmake --preset Release`。
5. **烧录**：`tools\flash.ps1 Release`。
6. **串口**：COM9 @115200；抓包 `python tools\hosttest\test_capture.py --port COM9`。
7. **硬件接线表**：传感器 VCC/GND/SDA/SCL/ADDR/INT → F411 引脚；**INT → PB5，外接 10 kΩ 上拉到 3.3 V**；I2C PB6/PB7；UART PA9/PA10。
8. **宿主单元测试**：`tools\hosttest\run_tests.ps1`。
9. **屏幕支持暂缓说明**：ST7789 代码保留在 `Drivers/ST7789/`，本轮不参与构建。
10. **Git 策略说明**：HAL/CMSIS 不入库，依赖本机 CubeF4 包。

- [ ] **Step 3: 在 spec §5.3.1 末尾补实测结论**

在 §5.3.1 的"实测计划"段落之后追加一行：

```
**实测结论（2026-11-07）**：见 `docs/superpowers/plans/2026-11-07-sample-rate-sweep-results.md`。
默认工作点 = ____ Hz，推荐上限 = ____ Hz，瓶颈 = ____。
```

- [ ] **Step 4: 提交**

```
docs: 补充协议 v1.2 正式文档与项目 README

协议文档覆盖三类 12 字节帧、CRC-8 golden vector、量程-灵敏度对照表、
错误码表与 Python 参考实现。README 覆盖构建/烧录/串口/接线/宿主测试。
```

---

## Self-Review

**Spec 覆盖检查**

| Spec 章节 | 对应任务 |
|---|---|
| §5.1 目录结构 | Task 1、2、6 |
| §5.2 传感器配置（逐位） | Task 5 |
| §5.3 采样模型 | Task 6 |
| §5.3.1 采样率上限与扫频 | Task 8 |
| §5.4 协议 v1.2（三类帧 + 错误码表） | Task 4、9 |
| §5.5 工程管理约定（.ioc 不生成、手工同步） | Task 1（.ioc 随仓库保留）、Task 6（手工写 PB5/EXTI） |
| §6.1 工具链 | Task 2、7 |
| §6.2 HAL/CMSIS 定位 | Task 2 |
| §6.3 .gitignore | Task 1 |
| §6.4 ST7789 处置 | Task 1（保留）、Task 2（不参与构建） |
| §7 PC 端 | → 另一份计划 `2026-11-07-tmag3001-host-viewer.md` |
| §8 风险 R1/R2/R3/R5/R6 | Task 6（R1/R2）、Task 7（R3）、Task 4（R6）、Task 8（R5） |
| §9 验收 A1–A10 | Task 1–8 各自对应（A1→T2、A2→T7、A3/A4→T7、A10→T8） |

**无遗漏**：A5/A6/A7/A8/A9 属 PC 端范围，在另一份计划中验收。

**占位符扫描**：本计划无 TBD/TODO；所有代码块给出完整内容；所有"预期输出"均具体。

**类型一致性核对**：
- `tmag_sample_t` 字段 `x_raw/y_raw/z_raw/temp_raw` — Task 4 定义，Task 6 使用 ✓
- `tmag_status_t` 字段 `flags/range_code/sensitivity/sample_rate_hz/err_count/conv_status/device_status` — Task 4 定义，Task 6 使用 ✓
- `TMAG_FLAG_*` 位定义 — Task 4 定义，Task 6 使用 ✓
- `TMAG3001_Data_t` 增加 `x_raw/y_raw/z_raw/temp_raw` — Task 5 定义，Task 6 使用 ✓
- `App_Init(UART_HandleTypeDef*, I2C_HandleTypeDef*)` — Task 6 定义并使用 ✓
- `tmag_sensitivity_for_range()` — Task 4 定义，Task 6 调用 ✓
- `tmag_encode_data/status/error` 返回 `size_t`，Task 6 比较 `== TMAG_PROTO_FRAME_SIZE` ✓
- Task 6 中 `App_Init` 签名与 Task 2 占位版本（`void App_Init(void)`）不同 —— Task 6 会整体替换占位文件，已在 Task 6 Step 3 注明"替换占位" ✓
