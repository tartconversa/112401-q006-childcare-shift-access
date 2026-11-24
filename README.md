# 轮班家庭的托育覆盖测算与连带席位确认

托育点和雇主以同一组日历日交接两周班表。所有钟点为本地当天时刻，起点计入区间、终点不计入。交通分钟是同一接送人的单程预留时间。

## 资料约定

CSV 使用 UTF-8，首行为列名。多值字段以竖线分隔。空单元格表示来源未填。

- families.csv。优先组数字小者优先。同组按 joined 顺序等待。worker_site 是雇主工作地点，caregiver 是家庭中可安排接送的人。
  字段为 `family`、`priority`、`joined`、`worker_site`、`caregiver`、`latest_start`。
- children.csv。儿童与年龄班。pickup_allowed 是哪些接送人具有实际接送资格。
  字段为 `child`、`family`、`class`、`pickup_allowed`。
- shifts.csv。同一 option 底下各行是一个完整班型所需的日期与时段。state 为 firm 或 provisional。
  字段为 `option`、`family`、`day`、`start`、`end`、`state`。
- rooms.csv。开班容量与实际配置的看护时段，staff_limit 是同一看护组在相交时段可照护的总人数。
  字段为 `room`、`centre`、`class`、`day`、`start`、`end`、`seats`、`staff_group`、`staff_limit`。
- travel.csv。演练接送的对称行程。home 对该家庭表示各自起终点，样本共用时长。
  字段为 `place_a`、`place_b`、`minutes`。
- offers.csv。业务台账中的既有确认、邀约及候补。多名儿童、多日期要求使用同一 offer 交接，派位单的状态记录家庭接受程度。
  字段为 `offer`、`family`、`child`、`room`、`state`、`asof`。
- changes.csv。照护点提交的临时减班或规划试算材料。kind 决定适用现场还是规划情景。
  字段为 `change`、`kind`、`room`、`start`、`end`、`seats`、`notice`。

## 检查演练资料

使用 Python 3.11.2 标准库，无需安装第三方依赖。在项目根目录运行下列命令可检查 CSV 读取、资料关联及样例记录完整性。

```bash
python3 -m unittest discover -s tests -v
```
