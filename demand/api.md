为此项目，实现后端服务接口，根据本项目不同场景实现不同的特点（在协议范围内的），你建议后端api服务怎么进行构建呢

固化judge/attribute/live（实时业务系统请求）/mock/view/trace/前端表格view的后端接口

前端对应位置信息，统一通过后端api调用进行获取，并且字段对齐，后端通过fastapi实现，需要

schema数据流/后端实现/api服务/前端实现/整体协议请对齐

涉及后端api接口的直接输入输出部分，请完全基于现有schema构建

# 迁移方案
当前本项目的api路由实现转移到verifier/impl/server文件夹中，暂且不要大改路由地址（只改路由实现变为fastapi），保持大部分接口一致性，如果当前有缺的路由先补一下


# 测试套件

测试api*项目的交叉测试套件
- 通过fixture构建测试用例case
- 将fixture喂给api服务进行调用
- 检验结果是否符合预期，是否满足与下游依赖schema相对应

测试套件放在verifier/hooks/api-check
测试套件请进行可实话，让用户能看到各api的输入输出情况，从而判断api是否正常

我要的东西很简单，构建fixture，fixture输入到api，api返回结果，结果校验为预期schema，就行了

我觉得测试套件应该做一个以curl为核心的表格报告，记录输入的请求体，测试的项目,测试的api接口，输出的结果，由于是api请求肯定都是可以格式化出来的，然后记录到一个csv表里面，可以通过转换请求体类型来测不同的东西，然后要做api和项目的交叉测试
表格文件放在verifier/report/api-check/{timestamp}/api-check.xlsx