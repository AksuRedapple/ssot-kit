# inbox · 贡献入口

> 任何会话把「值得长期留下的」按行**追加**（一天一文件，或主题文件）。
> 行格式：
> `- YYYY-MM-DD [fact|decision|insight|assertion|state] 内容 | source: <出处> | line: <线索> | owner: <谁定的> | conf: <实测|推断|待核>`
>
> `conf` 可选但推荐给关键数字：**实测**=本机跑过/核过；**推断**=由证据推出、未直接复现；**待核**=单一来源/未核验。缺省=未标（不算错，但不计入覆盖率）。

红线：

1. 只追加，不改已写行（提纯后在行尾加 `→ 归位:<目标>`）
2. fact 无 source / decision 无 owner = 无效行
3. 单向提纯：inbox → knowledge/lines，永不反向
