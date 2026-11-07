# 执行状态（2026-11-07）

分支 `codex/tmag-pipeline`，仅本地提交，未 push。交接材料基础为 `893bafd`；旧接手命令中的 `6f71096` 已过时。保留后续 `772dfed` 时钟文档与 `296ec26` 交接状态更新；实际 HEAD 以 git log 为准。

| 计划任务 | 当前事实 |
|---|---|
| Plan A Task1 归集 | 已完成 `49ec2c8`；29个归集文件两次运行SHA一致；26个文本为UTF8无BOM；HAL/CMSIS未入库；cmake仅两个工具链文件；两轮独立审阅通过 |
| Plan A Task2 构建系统 | 已实现并完成本机 Release/Debug 构建；两轮独立审阅待完成；完整应用留Task6 |
| Plan A Task3 宿主测试骨架 | 已完成 `80ae32e`；两轮独立审阅通过 |
| Plan A Task4..9 | 待实施；本次仅提前修正文档契约 |
| Plan B Task1..10 | 待实施 |

任务号 A1/A2/A3 在上表指 Plan A Task1/2/3，不能与 spec 的硬件验收ID A1..A10混为一谈。Task2 的本机构建不代表完整采集应用或硬件链路验收；完整应用、烧录、串口抓包及扫频仍待后续任务完成，未将历史遗产构建视作新链路验收。

已解决的文档问题：500/1000 Hz 被 uint8 截断；RATE_X10与名义/实测速率混淆；错误帧示例13 B；7 B XOR误写B3；状态unpack把H误拆两值；F411中断向量误写EXTI5；Task1递归cmake复制与文字矛盾；Task2排除ST7789后main仍调用UI。canonical协议保持12 B/0x12，新增高采样率向量；速率契约已通过两轮审阅及计划内 Python 协议测试的 30 次内存调用，实际 C 编解码实现与验证仍待 Task4，PC 应用仍待 Plan B。

后续阻塞实现缺陷已写入固件计划：Task5触发控制字节T位=0x80、Init保留扫描地址；Task6显式armed、独立名义调度时基、验证后INT_PATH_OK、UART DMA队列竞态测试。旧Task6伪代码被明确的实施要求取代，不可照抄。触发依据为本地datasheet §6.5.1.1 PDF第24页。

本文区分计划片段检查与实际实现验收；Task2 的本机 Release/Debug 构建如上表所记，不宣称运行时协议或硬件测试已通过。已独立确认五组黄金向量均12字节且XOR正确；在内存执行计划中的Python协议/抓包片段，核对100/500/1000 Hz向量、边界值、拒绝非法速率、HSE保留、RATE_X10重算及版本拒绝；六份文档UTF8无BOM，diff空白检查通过。这些检查不是实际固件或PC应用运行时验收。PC 计划已修正 HSE 期望位与全局 SEQ 检查（`07e4419`），并补充 B6 实施要求：分别记录重同步跳过字节与 SEQ 丢失帧数，以噪声/损坏帧测试防止单位混加。

> Device_Status 更正（datasheet §7.1.29，PDF第57页）：bit4 INT_RB、bit2 INT_ER、bit1 OTP_CRC_ER、bit0 THR_Cross，没有 overflow 位。0x08 OVERFLOW 仅保留兼容编号，无已证实溢出条件不得发出；THR_Cross/INT_RB 不得当溢出。INT_ER/OTP_CRC_ER 映射 ERR_SENSOR_DIAG。Task5/6 必须读取并上报实际 Device_Status，不得始终发送初始化0；需驱动/应用测试验证。
