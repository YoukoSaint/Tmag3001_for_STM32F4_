# 执行状态（2026-11-07）

分支 `codex/tmag-pipeline`，仅本地提交，未 push。交接材料基础为 `893bafd`；旧接手命令中的 `6f71096` 已过时。保留后续 `772dfed` 时钟文档与 `296ec26` 交接状态更新；实际 HEAD 以 git log 为准。

| 计划任务 | 当前事实 |
|---|---|
| Plan A Task1 归集 | 已完成 `49ec2c8`；29个归集文件两次运行SHA一致；26个文本为UTF8无BOM；HAL/CMSIS未入库；cmake仅两个工具链文件；两轮独立审阅通过 |
| Plan A Task2 构建系统 | 已完成 `73ca5cb` + `ee304e4`；Release/Debug 构建，两轮独立审阅通过 |
| Plan A Task3 宿主测试骨架 | 已完成 `80ae32e`；两轮独立审阅通过 |
| Plan A Task4 协议 | 已完成 `80000c3`；C 147项检查，两轮独立审阅通过 |
| Plan A Task5 驱动 | 已完成 `7d2f8f8` + `60b4f85`；2068项检查，两轮独立审阅通过 |
| Plan A Task6 应用 | 已完成 `1d4afe8` + `6727a16` + `681823d`（DMA恢复修正）；1353项应用检查及速率矩阵，两轮独立审阅通过 |
| Plan A Task7 工具/硬件 | 工具已实现；13项模拟串口/JSON检查通过，两个PowerShell脚本语法检查通过；待独立审阅；尚未烧录、探测或抓取真实串口，硬件操作由主任务统一执行 |
| Plan A Task8/9 | 待实施 |
| Plan B Task1 | 已完成 `90b7278`，两轮独立审阅通过 |
| Plan B Task2 | 已完成 `16fe886`；92项测试，两轮独立审阅通过 |
| Plan B Task3 | 已完成 `2567057`；6项测试，两轮独立审阅通过 |
| Plan B Task4 | 已完成 `c90298b` + `1eb9285`；46项测试，两轮独立审阅通过 |
| Plan B Task5 | 已完成 `4c6da00`；29项测试，两轮独立审阅通过 |
| Plan B Task6 | 已实现 `4ffe097` + `92d1e95`；28项测试，审阅进行中 |
| Plan B Task7 | 已完成 `4f58e17`；23项测试，两轮独立审阅通过 |
| Plan B Task8/9/10 | 待实施；主窗口须等待Task7硬件验收 |

表中任务号指 Plan A/B 的 Task，不能与 spec 的硬件验收ID A1..A10混为一谈。最新集中执行的 Release ARM 构建已通过且无警告（固件源代码范围 `681823d`）：text 35200 B、data 468 B、bss 2540 B，链接器报告 FLASH 35680 B / RAM 3008 B。构建与宿主测试不代表硬件链路验收；尚未进行烧录、真实串口抓包及扫频。

已解决的问题：500/1000 Hz 被 uint8 截断；RATE_X10与名义/实测速率混淆；错误帧示例13 B；7 B XOR误写B3；状态unpack把H误拆两值；F411中断向量误写EXTI5；Task1递归cmake复制与文字矛盾；Task2排除ST7789后main仍调用UI。canonical协议保持12 B/0x12；高采样率契约现已在实际 C/Python 编解码实现并测试，不再仅为计划代码片段。

Task5/6 已按修正后的实施要求完成驱动与应用，包括触发控制字节T位=0x80、Init保留扫描地址、显式armed、独立名义调度时基、验证后INT_PATH_OK及UART DMA队列竞态检查。触发依据为本地datasheet §6.5.1.1 PDF第24页。

本文区分计划片段检查与实际实现验收；Task2 的本机 Release/Debug 构建如上表所记，不宣称运行时协议或硬件测试已通过。已独立确认五组黄金向量均12字节且XOR正确；在内存执行计划中的Python协议/抓包片段，核对100/500/1000 Hz向量、边界值、拒绝非法速率、HSE保留、RATE_X10重算及版本拒绝；六份文档UTF8无BOM，diff空白检查通过。这些检查不是实际固件或PC应用运行时验收。PC 计划已修正 HSE 期望位与全局 SEQ 检查（`07e4419`），并补充 B6 实施要求：分别记录重同步跳过字节与 SEQ 丢失帧数，以噪声/损坏帧测试防止单位混加。

当前执行约束：不使用GUI，避免点击弹窗；硬件相关的本机构建、烧录、SWD探测和串口操作统一由主任务执行，其余工作仅做普通宿主检查。Task7 新工具默认 Release，探测默认仅枚举且不复位；抓包复用已批准的 `host/tmag_viewer/protocol.py`，默认要求有效状态帧，JSON保留全部有效帧与DATA原始值及时间。工具单元测试仅注入模拟串口，不连接COM9。工具测试通过不计作硬件通过。

> Device_Status 更正（datasheet §7.1.29，PDF第57页）：bit4 INT_RB、bit2 INT_ER、bit1 OTP_CRC_ER、bit0 THR_Cross，没有 overflow 位。0x08 OVERFLOW 仅保留兼容编号，无已证实溢出条件不得发出；THR_Cross/INT_RB 不得当溢出。INT_ER/OTP_CRC_ER 映射 ERR_SENSOR_DIAG。Task5/6 必须读取并上报实际 Device_Status，不得始终发送初始化0；需驱动/应用测试验证。
