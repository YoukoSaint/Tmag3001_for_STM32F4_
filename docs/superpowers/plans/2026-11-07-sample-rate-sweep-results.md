# 采样率扫频记录（2026-11-07）

## 修复抓包工具后的有效重测

`d2f3d3b`移除每轮串口重配后，使用当前有界总线恢复固件重新实际执行四档，每档20秒。证据为本机 `build/hardware/sweep-stable-timeout-02/`。本节优先于下面旧工具测量；历史表保留作对照。

| 配置Hz | DATA数量 | 实际DATA Hz | SEQ缺口 | 跳过字节 | ERROR帧 | 末状态累计错误 |
|---|---:|---:|---:|---:|---:|---:|
| 100 | 2003 | 99.836 | 0 | 0 | 0 | 0 |
| 200 | 4005 | 199.790 | 0 | 0 | 0 | 0 |
| 500 | 7806 | 389.696 | 89 | 7 | 0 | 168 |
| 1000 | 7247 | 362.350 | 0 | 0 | 1（I2C_TIMEOUT） | 50 |

100/200满足本次时间窗内连续无缺口及无故障；500不能跟上配置节拍并出现传输异常；1000发生I2C超时，虽末状态重新健康，脚本仍按整段ERROR拒绝并退出1，不将恢复后状态当作全程成功。高档累计错误涉及调度压力，具体比例未分项，不仅凭累计计数认定UART溢出。瓶颈至少包括I2C事务/调度吞吐；115200线速也不能容纳1000组12字节DATA加心跳。不能仅凭本次数据精确分配各瓶颈占比。

默认工作点保持100 Hz；本次测试范围内推荐上限200 Hz，限定为已测20秒健康窗口，未证明长期稳定或物理极限。默认100 Hz另有35.047秒3501 DATA、零缺口/错误的完整原始抓包。最终restoration.source_restored/rebuild_ok/reflash_ok全部true，failures=[]，已恢复100 Hz源配置并重新烧录。1000档I2C故障属于本次真实证据，不能隐去。

## 历史抓包工具结果（受每轮重配影响）

已实测四档，保持I2C 100 kHz、UART 115200、纯轮询；每档20秒。以下是当前链路的有界观测，**未证明无损稳定上限**，默认继续100 Hz。使用见[README](../../../README.md)，完整状态见[执行状态](2026-11-07-execution-status.md)。

| 配置 Hz | DATA数量 | 实际 DATA Hz | SEQ缺口 | 跳过字节 | 当前事实 |
|---|---:|---:|---:|---:|---|
| 100 | 1961 | 97.972 | 38 | 293 | 19状态、0 ERROR、末状态诊断正常、err_count=0 |
| 200 | 3923 | 195.993 | 131 | 516 | 19状态、0 ERROR、末状态诊断正常、err_count=0 |
| 500 | 7558 | 377.598 | 206 | 670 | 20状态、0 ERROR、末状态诊断正常、err_count=24；调度已积压 |
| 1000 | 17 | 0.849 | 140 | 4 | 20状态、18 I2C_NACK；末状态READY/CFG清零，健康门槛拒绝 |

每档elapsed_seconds约20.016；起止/开串口耗时计入，非精确稳态吞吐标定。500 Hz的err_count包含调度错误，不可仅凭0 ERROR认定无压力。1000 Hz的数据来自掉线前短暂采样，0.849不能解释为稳态采样能力。

SEQ按所有帧类型、模256推断；XOR可能碰撞，噪声误认会放大缺口，不能把数字全部视作已证明的物理丢帧。解析跳过量以字节计，不能与缺口相加。100/200均有缺口，因此不能推荐为已验证的无损档位。115200/8N1下12字节帧的纯理论上限约960帧/秒，还未扣除状态与错误帧，1000组DATA/秒超出该线速预算。

## 执行与恢复证据

```powershell
.\tools\sweep.ps1 -InitialCapture build/hardware/polling100-repeat4096.json -OutputRoot build/hardware/sweep-polling-01
```

实际执行非DryRun。先前健康基线983 DATA、97.840 Hz、0 ERROR满足进入条件。脚本依次修改、构建、烧录并抓取四档；1000档捕获完成后因末状态不健康退出1，未误判全部成功。

本机忽略目录 `build/hardware/sweep-polling-01/` 保存summary.json、各rate-N/capture.json、构建/烧录/抓包日志及原始app_config.h。summary.restoration为source_restored=true、rebuild_ok=true、reflash_ok=true、failures=[]。已核对默认100U及源文件恢复。该次扫频没有启用raw-out，只有accepted raw_hex，不能声称保存完整线流；基线与读取方式对照另有完整.bin。

1000档后，虽已恢复100 Hz，传感器仍无应答。只读SWD发现GPIOB_IDR=0x70（PB6高、PB7低）、I2C1_SR2=2（BUSY）。这证明总线处于SDA低的卡住状态，尚未证明起因是采样速率、烧录复位打断读事务或物理链路。后续固件加入有界总线恢复；该增量发生在本表测量后，不能据此改写结果。新固件与实机联调见执行状态。

## 重测方法

```powershell
.\tools\sweep.ps1 -DryRun
# 先取得健康100 Hz初始报告，再使用新的输出目录
.\tools\sweep.ps1 -InitialCapture build/hardware/healthy-new.json -OutputRoot build/hardware/rate-sweep-new
```

初始报告必须有有效状态与DATA、量程0、885 LSB/mT、READY/CFG置位、ConvStatus & 0x02及DeviceStatus & 0x06均清零，并无故障ERROR。实际测量允许TX_OVERFLOW作为瓶颈证据，其他传感器故障仍拒绝。结束/失败均进入源文件恢复、重建和重新烧录流程；必须同时核对restoration与退出码。
