# 轮班家庭的托育覆盖测算与连带席位确认

托育点和雇主以同一组日历日交接两周班表。所有钟点为本地当天时刻，起点计入区间、终点不计入。交通分钟是同一接送人的单程预留时间。

本项目为园区服务站回答三类问题：

1. **覆盖测算**：按家庭和班型，比较现状与拟增开服务（延长营业 / 增加人员）各能覆盖多少户，并指出阻断完整轮换周期的具体日期、孩子或接送段。
2. **连带派位**：在一项返岗选择上同时保住每个孩子的全部照护段，保留已接受的续托与看护限额，按公布的优先组和等待日期派位；跨两所点拼出的服务以一份联动邀约交接，半份接受不能独立成派位。
3. **闭园协商与周期复盘**：临时减班时先分清受牵连的整份邀约与仅存在于分析中的备用组合；家长确认替代或放弃后才释放时段；下一周期录入后比较规划覆盖与实际兑现并逐户解释差异。

## 资料约定

CSV 使用 UTF-8，首行为列名。多值字段以竖线分隔。空单元格表示来源未填。

- `families.csv`。优先组数字小者优先。同组按 joined 顺序等待。worker_site 是雇主工作地点，caregiver 是家庭中可安排接送的人。
  字段为 `family`、`priority`、`joined`、`worker_site`、`caregiver`、`latest_start`。
- `children.csv`。儿童与年龄班。pickup_allowed 是哪些接送人具有实际接送资格。
  字段为 `child`、`family`、`class`、`pickup_allowed`。
- `shifts.csv`。同一 option 底下各行是一个完整班型所需的日期与时段。state 为 firm 或 provisional。
  字段为 `option`、`family`、`day`、`start`、`end`、`state`。
- `rooms.csv`。开班容量与实际配置的看护时段，staff_limit 是同一看护组在相交时段可照护的总人数。
  字段为 `room`、`centre`、`class`、`day`、`start`、`end`、`seats`、`staff_group`、`staff_limit`。
- `travel.csv`。演练接送的对称行程。home 对该家庭表示各自起终点，样本共用时长。
  字段为 `place_a`、`place_b`、`minutes`。
- `offers.csv`。业务台账中的既有确认、邀约及候补。多名儿童、多日期要求使用同一 offer 交接，派位单的状态记录家庭接受程度。
  字段为 `offer`、`family`、`child`、`room`、`state`、`asof`。
- `changes.csv`。照护点提交的临时减班或规划试算材料。kind 决定适用现场还是规划情景。
  字段为 `change`、`kind`、`room`、`start`、`end`、`seats`、`notice`。

## 业务口径

### 接送链路

一位接送人在一个工作日内承担该家庭全部孩子的早送与晚接：

- 早：`home → 中心₁ → 中心₂ → … → 工作点`，从工时开始反推每个中心的最晚送达时刻；
- 晚：`工作点 → … → 中心₂ → 中心₁ → home`，从下班时刻正向推算到达每个中心的时刻。

多个孩子在不同中心时枚举中心访问顺序，只有某个顺序全程赶得上才算串接可行。孩子的必照护窗口是「最晚送达 → 实际接走」，该窗口必须落在房间一段**连续**开放时间内；临时闭园造成的零座位缺口会切断照护，不能用多段并集冒充连续看护。延时加段与原段首尾相接时视为连续。

### 两条覆盖口径与两条不确定带

- **可达性**只看房间开放与接送链路，不考虑座位争抢；
- **容量派位**在既有承诺之外逐户抢房间座位与看护组人员限额，回答实际能兑现多少返岗。

每条口径再分：

- **firm 带**：只统计 firm 工时行；只承诺一半班表（provisional）的日子不计入确定覆盖；
- **上沿带**：把 provisional 行也算入，反映雇主确认半日班表后的最好情况。

一个家庭申报多个班表选项也只贡献一次返岗机会。

### 三个情景

| 情景 | 包含的变更 | 含义 |
| --- | --- | --- |
| `current` | confirmed-closure | 现场口径，临时闭园/减班已生效 |
| `extension` | confirmed-closure + scenario-extension | 只延长营业、不加人手 |
| `staff` | confirmed-closure + scenario-staff | 延长营业且增加人员座位 |

容量同时受两个约束：房间 `seats`，以及同一 `staff_group` 跨房间在相交时段的 `staff_limit`。

### 派位与邀约状态

- `renewed`：已接受的续托，锁定原房间与照护窗，优先于一切新派位；
- `offered` / `accepted`：同一份联动邀约的明细。只要还有 `offered` 明细，整份就不算兑现，半份接受不能变成可独立使用的派位；
- `waiting`：候补，不占容量。候补家庭即使存在多个可行组合，也只有在能同时守住其他已发承诺时才收到选择。

候选家庭按「优先组 → 等待日期 → 家庭名」排序。可推迟但仍可维持返岗的备选开工日交给家庭决定；晚于 `latest_start` 仍无照护的日子显示为实际缺口。

## 命令

使用 Python 3.11 标准库，无需第三方依赖。隔离模式（`-I`）下通过根目录启动脚本运行，避免输入目录中的同名文件干扰导入：

```bash
# 覆盖测算：三情景 × 可达性/派位 × firm/上沿，附逐户诊断
python3 -I run.py coverage  samples

# 派位台账：既有承诺验算、按优先级派位、候补与开工日缺口
python3 -I run.py allocate  samples --scenario current
python3 -I run.py allocate  samples --scenario extension
python3 -I run.py allocate  samples --scenario staff

# 临时闭园影响：连带邀约协商清单 + 分析中的备用组合 + 释放时段
python3 -I run.py closures  samples

# 周期复盘：规划覆盖 vs 实际接受并完成接送，逐户解释差异
python3 -I run.py reconcile samples_next --planned samples
```

## 项目结构

```
carecycle/
  intervals.py    钟点/日期、左闭右开区间与合并工具
  models.py       CSV 行对应的不可变领域对象与 Bundle
  loader.py       七张 CSV 的读取、外键校验与资料装配
  scenarios.py    闭园/延时/加座变更切分，构造三个情景的开班段
  routes.py       接送链路验算（早送反推、晚接正推、中心顺序枚举）
  feasibility.py  班表选项逐日枚举房间组合，输出阻断日期与原因
  occupancy.py    扫线法核算房间座位与看护组人员双约束
  allocator.py    台账锁定、连带邀约、优先级派位、候补与开工日
  coverage.py     三情景 × 两口径 × 两不确定带的覆盖编排
  disruptions.py  闭园影响分级与家长协商后的台账更新/释放
  cycle.py        下一周期规划与实际兑现的逐户复盘
  reporting.py    中文表格报告（全角字符宽度对齐）
  cli.py          命令行入口
samples/          本周期演练资料（读取契约锚点）
samples_next/     下一周期台账，用于 reconcile 演示
tests/            读取契约 + 单元测试（28 个）
run.py            python -I 启动脚本
```

## 运行测试

```bash
python3 -I -m unittest discover -s tests -v
```
