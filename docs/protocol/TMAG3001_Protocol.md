# TMAG3001 串口线协议 v1.2（草案，待实现）

本文件是固件与 PC 的统一契约。当前导入的遗产代码不代表已实现本协议；实施/硬件验收状态见 [执行状态](../superpowers/plans/2026-11-07-execution-status.md)。版本字节为 `0x12`。串口默认 USART1 / 115200 / 8N1；无文本日志。

## 帧布局

所有帧固定 **12 字节**：`[0]=AA [1]=TYPE [2]=SEQ [3..10]=payload [11]=XOR`。TYPE 仅 `55` 数据、`56` 状态、`EE` 错误。SEQ 为所有帧类型共用、每帧递增的 uint8 序列（FF→00）；主机检查全部有效帧，不能只看数据帧。重启可重置序列；单次差值无法证明跨越多个 256 帧的丢失数量。

校验初值 0，对 **bytes[2:11]** 共 9 字节逐字节异或，结果放 byte11。同步头/TYPE 不参与校验。`crc8`/`tmag_crc8` 仅为兼容命名，**不是多项式 CRC-8**。遗产 7 B 负载 `01 05 D8 00 2C FF 1E` 的 XOR 为 **11**（不是 B3）。

数据帧 `55`：bytes3..4 X、5..6 Y、7..8 Z、9..10 TEMP，均 int16 大端原始 LSB。`mT=raw/sensitivity`；温度 `°C=(raw-17512)/58.2+25`。主机未收到有效状态灵敏度前不显示数值曲线。

状态帧 `56`：

| 字节 | 字段 |
|---|---|
| 3 | PROTO_VER=12；本版解析器拒绝其他版本，不猜布局 |
| 4 | FLAGS（见下） |
| 5..6 | uint16 大端 sensitivity，单位 LSB/mT |
| 7 | ENCODED_RATE，单位由 RATE_X10 决定 |
| 8 | 累计错误计数低 8 位（回绕） |
| 9 | CONV_STATUS 寄存器原值 |
| 10 | DEVICE_STATUS 寄存器原值 |

FLAGS bits0..1 RANGE：0=±40mT、1=±80mT、2=±120mT、3=±240mT，对应灵敏度 885/446/273/137 LSB/mT。bit2 SENSOR_READY；bit3 CFG_OK；bit4 TRIGGER_INT（1=INT 用作转换触发输入；0=I2C 命令触发，**与 data-ready 输出来源无关**）；bit5 INT_PATH_OK（实际验证 PB5 EXTI 完成路径后为1，启动不预设）；bit6 CLK_SRC_HSE（1=25 MHz 晶振，0=内部 HSI）；bit7 RATE_X10。

RATE_X10=0 时 byte7 单位 Hz；=1 时单位 10 Hz。编码规则：逻辑**整数 0..255** 直接表示，**256..2550 仅精确 10 的倍数**可表示；所有其他值拒绝，无四舍五入/截断。0 表示未知/未配置。编码器从逻辑 Hz 重算并清/置 bit7，保留 caller bit6，从 range_code 重算 bits0..1。C `sample_rate_hz` 为 uint16，非法值编码返回0且不修改 out；应用赋值不得先 cast uint8。Python 非整数（含 bool/float）、越界或不可表示值抛 ValueError。解码用 byte7×(bit7?10:1)，结果是**名义配置 Hz**，不是实测值。

固件毫秒调度器限制独立于线协议：`0 < APP_SAMPLE_RATE_HZ <= 1000` 且 `1000 % APP_SAMPLE_RATE_HZ == 0`，编译期保护；100/200/500/1000 Hz 支持整数周期。协议可表示更广范围不表示该调度器能产生这些速率。实际 Hz 由 PC 单独用数据帧计数/经过时间测量，状态/错误帧不计入；稳定上限仍须硬件扫频确定。

错误帧 `EE`：byte3 ERR_CODE、4 I2C_ADDR（7位地址，如34）、5 REG_ADDR、6..10 保留0。错误码：00 NONE/READY、01 I2C_NACK、02 SENSOR_ID、03 CONFIG_FAIL、04 I2C_READ、05 I2C_TIMEOUT、06 NO_CONV、07 SENSOR_DIAG、08 OVERFLOW、09 TX_OVERFLOW。未知错误码可展示为 UNKNOWN，不能改帧长。

## 五组跨语言 golden（十六进制）

```text
# data: seq01 x1496 y44 z-226 temp17512
AA 55 01 05 D8 00 2C FF 1E 44 68 3D
# status: seq42 version12 基础flags2C sens885 rate100 err0 conv1 dev0
AA 56 42 12 2C 03 75 64 00 01 00 6F
# same status, rate500 => encoded50, RATE_X10=1
AA 56 42 12 AC 03 75 32 00 01 00 B9
# same status, rate1000 => encoded100, RATE_X10=1
AA 56 42 12 AC 03 75 64 00 01 00 EF
# error: seq07 code01 addr34 reg0E
AA EE 07 01 34 0E 00 00 00 00 00 3C
```

流解析：扫描 AA → 检查 TYPE → 等待12 B → XOR → 状态检查版本12 → 分发。失败时滑动1 B重新同步；`struct.unpack(">BBHBBBB", payload)` 返回 **7 项**：version, flags, sensitivity, rate, errcnt, conv, devst（H 已是完整 sensitivity）。

> Device_Status 更正（datasheet §7.1.29，PDF第57页）：bit4 INT_RB、bit2 INT_ER、bit1 OTP_CRC_ER、bit0 THR_Cross，没有 overflow 位。0x08 OVERFLOW 仅保留兼容编号，无已证实溢出条件不得发出；THR_Cross/INT_RB 不得当溢出。INT_ER/OTP_CRC_ER 映射 ERR_SENSOR_DIAG。Task5/6 必须读取并上报实际 Device_Status，不得始终发送初始化0；需驱动/应用测试验证。
