# TripPilot

目标：把 Hello-Agents Chapter 13 智能旅行助手升级为一个适合 AI Application Engineer 求职的工程化项目。

## 最终定位

TripPilot 是一个：

**基于 LangGraph + MCP + RAG 的约束驱动、可验证、可恢复、可观测的智能旅行决策系统。**

目标流程：

User Query  
→ Constraint Extraction  
→ Parallel Retrieval  
→ RAG  
→ Candidate POIs  
→ Route Optimization  
→ Planner  
→ Validator  
→ Replan  
→ Final TripPlan

## 核心设计

### Agent / LLM

只负责：

- 自然语言理解
- 约束提取
- 用户偏好理解
- 行程规划
- 软约束判断
- Replan
- 最终解释

### Deterministic Code

负责：

- 预算计算
- 时间计算
- 距离计算
- 路线优化
- 排序过滤
- 硬约束检查
- Cache
- Retry / Timeout
- 持久化

### 核心模块

最终逐步具备：

- FastAPI
- LangGraph Workflow
- Structured TravelConstraints
- Parallel Retrieval
- Tool Runtime
- Redis
- MySQL
- Budget Engine
- Route Optimizer
- Structured TripPlan
- Validator + Replan
- Travel RAG
- Model Gateway
- Observability
- Evaluation
- Vue Frontend
- Docker

## 关键约束

最终 Validator 至少能检查：

- 总预算
- must visit
- avoid places
- 行程时间冲突
- 最大交通时间
- 每日步行限制
- 景点重复
- 开放时间冲突

软约束可由 LLM 辅助判断。

## RAG

RAG 用来支持旅行决策，而不是做普通 PDF 问答。

主要知识：

- 景区开放时间
- 预约政策
- 景区规则
- 无障碍信息
- 节假日规定
- 官方旅行信息

引用必须来源于真实检索 metadata。

## Evaluation

最终至少评估：

- Constraint Extraction Accuracy
- Constraint Satisfaction Rate
- Tool Success Rate
- Planning Success Rate
- P50 / P95 Latency
- Token Usage
- Cost
- Cache Hit Rate

## Phase

0. 分析现有源码
1. 基础配置、日志、异常
2. Constraint Engine
3. LangGraph 基础 Workflow
4. Retrieval Service + asyncio 并行
5. Tool Runtime
6. Redis
7. MySQL
8. Budget Engine
9. Route Optimizer
10. Structured Planner
11. Validator + Replan
12. RAG
13. Model Gateway
14. Observability
15. Evaluation
16. Frontend
17. Docker + CI
18. README + Benchmark + Resume

原则：每个 Phase 基于已有代码渐进式实现，不允许一次性重写整个系统。