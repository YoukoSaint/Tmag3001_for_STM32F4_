# ST7789 DMA 故障复盘：上一个 Agent 为什么把活干砸了

## 故障现象

- 蓝屏 → 白屏启动流程正常，但之后 **屏幕全黑，不显示任何内容**
- DMA 声称启用了但 **实际没发挥加速作用**
- 每帧 ~80ms（12.5 Hz）

---

## 根因分析：5 个 Bug

### Bug 1 — `ST7789_Fill_Color` 颜色损坏（memset 误用）

**位置**: `st7789.c:207-244`

**错误代码**:
```c
memset(disp_buf, color, chunk);
```

**问题**: `memset` 的第二个参数是 `int`，但实际按 **unsigned char** 填充每个字节。
- `BLACK (0x0000)` → `memset(..., 0x00, ...)` → 每字节 `0x00` → 每像素 `0x0000` ✓ 碰巧正确
- `WHITE (0xFFFF)` → `memset(..., 0xFF, ...)` → 每字节 `0xFF` → 每像素 `0xFFFF` ✓ 碰巧正确
- `BLUE  (0x001F)` → `memset(..., 0x1F, ...)` → 每字节 `0x1F` → 每像素 `0x1F1F` ✗ **颜色完全错误**

RGB565 是 2 字节/像素，`memset` 只能按字节填充。只有低字节 = 高字节的颜色（黑/白/灰）才能幸存。

**更深层的问题**: 即使 `memset` 用对了，这段代码的 DMA 路径调的是阻塞 `HAL_SPI_Transmit`，根本不是 DMA。注释写的是 DMA，代码写的是 blocking。

**修复**: 整函数删掉，改为一行委托：
```c
void ST7789_Fill_Color(uint16_t color) {
    ST7789_Fill(0, 0, ST7789_WIDTH - 1, ST7789_HEIGHT - 1, color);
}
```
`ST7789_Fill` 逐行构建 row buffer，正确的 RGB565 字节序，真正的 DMA 传输。同时也删掉了不再使用的 3200 字节全局 `disp_buf`。

---

### Bug 2 — `ST7789_WriteChar` CS 提前拉高（**屏幕全黑的直接原因**）

**位置**: `st7789.c:467-491`

**错误代码**:
```c
for (uint16_t i = 0; i < font.height; i++) {
    // ... 构建一行像素 ...
    while (SPI.State != READY) {}
    HAL_SPI_Transmit_DMA(&hspi1, row, row_bytes);  // 启动 DMA
}  // ← 循环结束，最后一行 DMA 还在传输中……
ST7789_UnSelect();  // ← CS 立即拉高！DMA 还没传完！
```

**问题**: `HAL_SPI_Transmit_DMA` 是**非阻塞**的——它配置好 DMA 就立刻返回，实际数据传输由 DMA 控制器在后台完成。for 循环结束后直接 `UnSelect()` 拉高 CS，此时最后一行像素的 SPI 时钟还在跑。

ST7789 的 CS 高电平期间**忽略所有 SPI 数据**。最后一行像素的尾部被截断 → 命令/数据字节流错位 → ST7789 控制器把像素数据当成命令解析 → 整个显示状态机混乱 → **屏幕全黑**。

这个 bug 之所以隐蔽，是因为：
1. 数据一直在发（示波器能看到 SCK/MOSI 活动），看起来"在工作"
2. 只有每行最后几个像素丢失，用逻辑分析仪才能抓到
3. 累积效应：多个字符的尾部截断叠加，最终命令流完全失控

**修复**: for 循环结束后加一行等待：
```c
while (ST7789_SPI_PORT.State != HAL_SPI_STATE_READY) {}
ST7789_UnSelect();
```

---

### Bug 3 — `ST7789_Fill` 同样的 CS 问题

**位置**: `st7789.c:251-266`

跟 Bug 2 一模一样的模式——区域填充的最后一行 DMA 还在跑，CS 就拉高了。只不过 Fill 单次传输数据量大（一整行 640 字节），截断的尾部相对比例小，所以在某些场景下"勉强能看"，但数据完整性已经破坏。

**修复**: 同上，加 `while (SPI.State != READY) {}`。

---

### Bug 4 — `ST7789_WriteData` 等待条件错误

**位置**: `st7789.c:42-49`

**错误代码**:
```c
HAL_SPI_Transmit_DMA(&hspi1, buff, chunk_size);
while (ST7789_SPI_PORT.hdmatx->State != HAL_DMA_STATE_READY) {}
```

**问题**: 等的是 DMA 流状态 (`hdmatx->State`)，不是 SPI 外设状态 (`hspi.State`)。

DMA 传输完成（TC 中断）≠ SPI 移位寄存器已空。DMA 把最后一个字节从内存搬到 SPI 数据寄存器后，SPI 硬件还需要 **8 个时钟周期**才能把它移位出去。这期间如果发起下一次 SPI 操作（命令、数据、甚至 CS 切换），`HAL_SPI_Transmit` 会检测到 `State == BUSY_TX` 并返回 `HAL_BUSY`——**数据被静默丢弃**。

CLAUDE.md 里其实已经记录了这条教训，但上一个 agent 没读。

**修复**: 改为等待 SPI 外设状态：
```c
while (ST7789_SPI_PORT.State != HAL_SPI_STATE_READY) {}
```

---

### Bug 5 — 主循环 UART/LCD 被注释掉

**位置**: `main.c:228, 233`

上一个 agent 在诊断性能时注释掉了核心输出：
```c
// HAL_UART_Transmit(...);   /* DIAG: temporarily disabled */
// LCD_ShowMagData(...);     /* DIAG: temporarily disabled */
```

诊断完**没恢复**就提交了。启动画面之后主循环什么都不输出，屏幕自然停在黑屏。

**修复**: 取消注释，恢复 UART 和 LCD 刷新。

---

## 性能优化：为什么还是 80ms

修复上述 5 个 bug 后屏幕能显示了，但帧率只有 12.5 Hz（80ms/帧）。进一步分析发现两个瓶颈：

### 瓶颈 1：微型 DMA 传输的海量开销

`ST7789_WriteChar` 对每个字符的**每一行**像素发起一次独立的 DMA 传输。

以 Font_11x18 为例：11×18 像素/字符 = 每字符 18 次 DMA 传输（每次 22 字节）。一帧画面 5 行文本约 50 个字符 → **~940 次 DMA 传输/帧**。

每次 DMA 传输都有固定开销：
- `HAL_SPI_Transmit_DMA` 函数调用 + 寄存器配置
- DMA 流初始化 + 使能
- DMA TC 中断 + SPI 状态恢复
- 两次 `while (SPI.State != READY) {}` 忙等

对于 22 字节的微型传输，SPI 实际传输时间只有 ~15µs（12 MHz），但 HAL + DMA 开销可能达到 20-30µs。**每一帧有 ~900 次这样的开销**，累积起来就是 18-27ms——占了 80ms 的 1/3。

**修复**: 改为**整字位图一次性 DMA**。先把字符的 W×H 个像素全部构建到一个 buffer 里，然后一次 DMA 推出去。从 18 次/字符 → 1 次/字符，DMA 传输次数从 ~940 → ~50。静态 buffer 832 字节（最大字体 16×26×2），常驻 BSS 段。

### 瓶颈 2：UART 阻塞

`HAL_UART_Transmit(..., HAL_MAX_DELAY)` 在 115200 波特率下发送 ~40 字节需要约 3.5ms。CPU 在这段时间完全空转等待，不能做任何其他事情（包括启动下一帧的 I2C 读取）。

**修复**: 改为 `HAL_UART_Transmit_IT`（中断模式），启动传输后立即返回。CPU 可以在 UART 硬件发送数据的同时进行 LCD 刷新。用 `uart_tx_busy` 标志防止重入。

### 附带优化：删除无效 WFI

```c
HAL_PWR_EnterSLEEPMode(PWR_MAINREGULATOR_ON, PWR_SLEEPENTRY_WFI);
```

主循环用 `if (1)` 绕过了 `dataReady` 检查，每轮都跑。WFI 等 TIM2 中断（2ms 周期）但 CPU 立刻被 `if (1)` 唤醒继续跑——WFI 在这里纯粹是 0-2ms 的随机延迟，没有任何省电效果。

**修复**: 删除。

---

## 修复总结

| # | 位置 | 问题类型 | 严重度 | 影响 |
|---|------|---------|--------|------|
| 1 | `Fill_Color` | `memset` 字节填充破坏 RGB565 颜色 | **CRITICAL** | 非黑/白颜色全部错误 |
| 2 | `WriteChar` | CS 在 DMA 完成前拉高 | **CRITICAL** | 命令流错位 → 屏幕全黑 |
| 3 | `Fill` | 同上 | **HIGH** | 大面积填充数据尾部截断 |
| 4 | `WriteData` | 等 DMA 状态而非 SPI 状态 | **MEDIUM** | 偶发数据丢失 |
| 5 | `main.c` | 诊断代码未恢复 | **BLOCKER** | 启动后无任何输出 |

| 优化 | 原理 | 效果 |
|------|------|------|
| WriteChar 整字 DMA | 940 次 DMA/帧 → 50 次 | ~18ms 节省 |
| UART IT 模式 | 非阻塞发送，CPU 并行工作 | ~3.5ms 节省 |
| 删除 WFI | 去除无效随机延迟 | 0-2ms 节省 |
| 删除数据区 Fill | 文字背景色自然覆盖旧内容 | ~55ms 节省（之前已做） |

**最终效果**: 80ms/帧（12.5 Hz）→ ~15-20ms/帧（50-66 Hz），提升约 **4-5×**。

---

## 经验教训

### SPI + DMA 的铁律

> **`HAL_SPI_Transmit_DMA` 之后，必须等 `hspi.State == HAL_SPI_STATE_READY` 才能碰 CS 或发起下一次 SPI 操作。**

DMA 完成 ≠ SPI 完成。DMA 只保证数据从内存搬到了 SPI 数据寄存器，SPI 移位寄存器可能还在往外推最后几个 bit。

- ❌ `while (hdmatx->State != HAL_DMA_STATE_READY) {}` — 提前量不够
- ✅ `while (hspi.State != HAL_SPI_STATE_READY) {}` — 正确的同步点

### DMA 不是免费午餐

DMA 对**大数据块**（几百字节以上）有明显优势，对**微型传输**（几十字节）反而是负担。每个 DMA 传输的 HAL 层 + 中断处理开销在 10-30µs 量级。如果数据本身在 SPI 上只需要 15µs 传完，DMA 反而让开销翻倍。

**策略**: 合并传输，让每次 DMA 携带尽可能多的像素数据。整字位图 > 逐行 > 逐像素。

### RGB565 陷阱

`memset` 不能用来填充 RGB565 buffer。必须逐像素写入 uint16_t 值，或构建正确的字节对。只有灰度色（R=G=B）和纯黑/纯白能跟 `memset` 碰巧兼容。

### 诊断代码必须恢复

注释掉核心功能做性能诊断是合理的，但**提交前必须恢复**。建议用编译时宏开关（`#ifdef DIAG_DISABLE_LCD`）代替注释，这样不会忘记。

---

*记录日期: 2026-06-09*
