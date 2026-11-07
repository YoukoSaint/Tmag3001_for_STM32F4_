# 执行状态（2026-11-07）

分支 `codex/tmag-pipeline`，仅本地提交，未 push，实际提交顺序以 `git log` 为准。Plan A/B Task 与 spec 硬件验收 A1..A10 是两套编号。使用步骤及验收表见[README](../../../README.md)，线协议见[统一契约](../../protocol/TMAG3001_Protocol.md)。

## 实施进度

| 计划任务 | 当前事实 |
|---|---|
| Plan A Task1 归集 | 完成 `49ec2c8`；29个文件两次归集 SHA 一致，26个文本 UTF-8 无 BOM；HAL/CMSIS 未入库；已独立审阅 |
| Plan A Task2 构建 | 完成 `73ca5cb` + `ee304e4`；Release/Debug 构建及独立审阅通过 |
| Plan A Task3 测试骨架 | 完成 `80ae32e`，已独立审阅 |
| Plan A Task4 协议 | 完成 `80000c3`；147项 C 检查，已独立审阅 |
| Plan A Task5 驱动 | 完成 `7d2f8f8` + `60b4f85`；2068项检查，已独立审阅 |
| Plan A Task6 应用 | 默认轮询 `2e9bede` 已审阅并实测；`682e67e`增加有界I2C总线恢复，独立审查通过；636项总线恢复/679项轮询/2253项INT检查及默认/0/1模式速率矩阵通过 |
| Plan A Task7 工具/硬件 | `c6113de` + `c114f41` 工具与新鲜度保护已审阅；真实烧录、状态、故障及健康DATA均已观测；无损连续门槛未通过 |
| Plan A Task8 扫频 | 工具及93项安全检查已审阅；100/200/500/1000 Hz均实测，1000档健康门槛失败；已还原源文件/构建/烧录100 Hz，见[记录](2026-11-07-sample-rate-sweep-results.md) |
| Plan A Task9 文档 | README、协议、状态、扫频及上位机验收记录按实测整理；硬件待验收项保留 |
| Plan B Task1 | `90b7278` 完成并审阅 |
| Plan B Task2 | `16fe886`，92项测试，完成并审阅 |
| Plan B Task3 | `2567057`，6项测试，完成并审阅 |
| Plan B Task4 | `c90298b` + `1eb9285`，46项测试，完成并审阅 |
| Plan B Task5 | `4c6da00`，29项测试，完成并审阅 |
| Plan B Task6 | `4ffe097` + `92d1e95` + `8582ff0`，串口生命周期保护完成并审阅 |
| Plan B Task7 | `4f58e17`，23项测试，完成并审阅 |
| Plan B Task8 | 主窗口与配色控制 `660a86d`，交替错误节流 `a4427c5`、ERR_NONE 处理 `c2b1645` 完成并通过质量审阅；主窗口及颜色面板29项离线测试通过 |
| Plan B Task9 | `7a0367e`，离线合成/真实故障回放通过；35秒实机曲线/CSV/日志/退出联调通过，A4零缺口门槛单独未通过；已集中独立审查 |
| Plan B Task10 | `7a0367e`中的spec仅打包模板且已审查；未安装/执行PyInstaller，无已验证分发包 |

解析/抓包修正 `8366e09` 已审阅：严格检查ERROR保留字节、可选raw-out及flush-input、原始字节偏移/完整性；`722e54c`澄清raw_complete。`7a0367e`增加显式read-size实验参数、无窗口验收及实机健康门槛。最终宿主/抓包/验收合并319项通过（13.45秒）。离线测试不是硬件通过的替代证据。

## 已验证的硬件事实

ST-Link SN `004800454A00001156313848`，固件V2J46M33，COM9确认为该ST-Link的VCP；目标F411xC/E，device ID 0x431、512 KB FLASH，目标电压3.24 V，CPUID `0x410FC241`。`682e67e` Release已真实写入、-v校验并复位成功，无警告：text 36000 B、data 468 B、bss 2540 B；链接器FLASH 36480 B / RAM 3008 B。ELF SHA256：

```text
63E3DAD540AB7647A2FD6ACDEEB4DB8E0FD6E7B1F953634DAE564305092773EE
```

串口 COM9 / 115200；以下报告在本机 `build/hardware/`，按忽略规则不入库。报告中的缺口为解析结果，不能一概称作物理丢帧。

| 本机记录 | 观测事实 |
|---|---|
| `t7-initial.json` | I2C NACK；18有效帧、10状态、0 DATA；推断缺口1、跳过6字节；flags=0x50 属旧触发标志语义 |
| `t7-postflag.json` | 传感器0x34响应、配置回读成功；flags=0x4C、sens=885、名义100 Hz；Device=0x14、Conv=0xF3/0x73；992有效帧、982诊断错误、0 DATA；旧解析报告缺口16、跳过107字节 |
| `t7-int-recovery.json` | 有界历史 INT 清除后仍 Device=0x14、Conv=0x73；1003有效帧、11状态、992诊断错误、0 DATA；旧解析报告缺口123、跳过159字节 |
| `polling100-fresh1.json` + `.bin` | 默认纯轮询初次健康：989 DATA、98.447 Hz、0 ERROR，Device=0x10，flags=0x4C；11 SEQ缺口、63跳过字节 |
| `polling100-read1.json` + `.bin` | 每次1字节读取实验显著恶化：105 DATA、0状态、必需状态检查失败；不采用该读取方式 |
| `polling100-repeat4096.json` + `.bin` | 默认读取对照：983 DATA、97.840 Hz、0 ERROR；15缺口、100跳过字节 |
| `sweep-polling-01/summary.json` | 四档实测，1000档末状态不健康退出1；源文件恢复、重建及重新烧录全部成功 |
| `polling100-bus-recovery-final.json` + `.bin` | 总线恢复固件：994 DATA、98.945 Hz、0 ERROR、诊断位正常、累计err_count=1；211推断缺口、113跳过字节，详见下面限制 |
| `polling100-coldboot-01.json` + `.bin` | 用户断电重启后：979 DATA、97.442 Hz、10状态、0 ERROR、累计err_count=0、当前诊断正常；20缺口、141跳过字节，冷启动可采样但传输问题仍在 |
| `polling100-read64.json` + `.bin` | 保持固件不变改为64字节读取：985 DATA、98.039 Hz、0 ERROR；13缺口、131跳过字节，未消除问题，不据单次计数差异改变生产读取方式 |

历史INT报告发现过非零ERROR保留字节的XOR碰撞误认，不能认定123缺口均为物理丢帧。最新总线恢复后报告第10个接受帧从SEQ 242跳到185，随后连续186；仅这一次模256跳变就贡献198缺口。可能涉及旧缓冲或流边界，但尚未定因，不能把211全算作10秒内物理丢失。flush-input仅记录执行过清输入动作，不证明设备端缓存和流边界已完全清洁；所有原始证据保留。

扫频后曾持续I2C无应答，SWD只读取得GPIOB_IDR=0x70（SCL高/SDA低）、I2C1_SR2=2 BUSY。`682e67e`按[NXP UM10204总线清理](https://www.nxp.com/docs/en/user-guide/UM10204.pdf)加入单控制器PB6/PB7开漏恢复：仅前台重连前检查，空闲不动；最多9个恢复时钟加STOP，等待有界（最长约22 ms），恢复HAL/AF，失败保留错误和重试节流。诊断清除策略不变。之后已重新取得健康DATA；卡住的触发原因尚未证明，不能直接归因于1000 Hz或模块损坏。

实机上位机 `build/host-acceptance/b9-live-poll100-recovery-02/`：35秒报告通过，3491 DATA、40状态、6 ERROR、3469行CSV；四曲线各2000点；当前metadata健康、885 LSB/mT、100 Hz，报告实际99.700 Hz。6条NACK在刚开始收到，后续健康；未清输入缓冲，不能证明它们属于当前运行。队列丢弃0、SEQ缺口112、跳过12字节；30秒自然HEALTH为CPU26.7%、RSS93.4 MiB、27线程。CSV逐行与收到的原始值/状态灵敏度核对通过，所有退出清理检查通过。STOP日志比快照多21 DATA，因截图/保存期间仍采样，不能混用时点。

## 契约与后续门槛

用户允许暂用轮询；当前APP_USE_INT=0、enable_int=0、INT_CONFIG1=0，按1 ms检查/5 ms超时，忽略PB5边沿且INT_PATH_OK始终0，已审阅和硬件验证。APP_USE_INT=1保留旧路径；Core/.ioc保留输入/IRQ。I2C触发语义与诊断门控不变。用户又要求后续尽可能主agent直接完成，已停止逐任务委派，仅集中独立审查；没有调整全局权限或绕过硬件访问限制。

12 B / 0x12 的 C 与 Python 协议已实施，五组 golden 保持不变；500/1000 Hz 用 bit7 RATE_X10 无损表示，配置 Hz 与实际 DATA Hz 分开。XOR 不是多项式 CRC；SEQ 共用于全部帧类型；重同步跳过字节、SEQ 缺口、主机队列丢弃分别统计。

DeviceStatus bit4 INT_RB 是回读，bit2 INT_ER 为 W1C、bit1 OTP_CRC_ER 为诊断，bit0 THR_Cross；没有 overflow 位，ERR 0x08 仅保留。当前 I2C 触发使状态 bit4 TRIGGER_INT=0，PB5 是完成输入；bit6 表示 HSE。`0732cf3` 仅在每次 App_Init 最多一次用0x04清历史 INT_ER，绝不清 OTP 或反复清故障。READY/CFG 加正灵敏度仍不足以证明健康，必须同时检查当前 ConvStatus 0x02 与 DeviceStatus 0x06 均清零。

验收：A1构建/A2烧录/A3状态/A5真实曲线/A6日志/A7故障门控/A8实机CSV值与原子收尾/A9忽略规则均已有证据；A4虽有健康DATA但零缺口门槛未通过。A10四档已测，无损稳定上限未证明。运行时物理拔线中断与EXE分发包未验证，不能据离线或健康35秒运行推断这些通过。用户冷启动已验证；下一步需区分MCU输出、物理UART线路、ST-Link VCP和主机读取边界，可用独立UART接收或逻辑分析对照，保持100 Hz基线。暂不升级ST-Link固件或改全局驱动，未向用户提出更换传感器要求。

当前保持无可见GUI，不安装依赖、不改全局配置、不push。硬件由主agent独占、任务内受控调用。用户断电期间停止硬件操作，确认重启后才重新抓包。

## 原始字节后续分析

主agent对冷启动、64字节读取、4096字节读取对照逐个SEQ缺口提取相邻有效帧之间的原始片段，结果保存在本机 `build/hardware/read-boundary-forensics.json`。冷启动20处缺口均有3..11字节残片；64字节读取13处均有8..11字节残片；4096字节读取对照15处有1..11字节残片。因此这些观测不能仅用主机交付队列丢弃完整12字节帧来解释，损坏/截断已经存在于解析前读到的线流。64字节读取仍未消除截断，当前证据不能定位是MCU发出、物理线路还是VCP/驱动接收；也未记录每次read边界，不能仅凭这些偏移宣布与read边界有关。保持原生产读取配置，不作无证据的固件改动。
