# 输出结果索引

论文当前方法使用根目录中的分层成立性与失效分析结果：

| 文件 | 用途 |
|---|---|
| `caseA_layered_results.json` | 案例A的上下文冲突、局部失败、边界失败、有效组合及两个顶事件结果 |
| `caseB_dual_display_results.json` | 双显示案例B的有效组合、并联失败及两个顶事件结果 |
| `scalability_results.json` / `scalability_summary.csv` | 正式重跑后生成的混合架构原始记录与汇总 |
| `scalability_*.png` | 正式重跑后生成的可扩展性实验图片 |

`auxiliary_regression/`保存旧版固定规则检查和旧割集输出，只用于回归对照，
不是论文分层判定表的直接证据。

方法边界调整前的规模实验文件已移至
`auxiliary_regression/pre_method_boundary_scalability/`。完成正式规模实验重跑后，
应在根目录重新生成三个规模结果文件和三张图片。
