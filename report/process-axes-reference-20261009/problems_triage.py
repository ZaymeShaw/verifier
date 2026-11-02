"""Triage every problem the two blind repetitions reported, against a fixed list of issues that stand up
on the case files (program-checked or backed by quoted rule text). The labels are MY judgement and are
written out explicitly so they can be disputed one by one.

Labels
  REAL:Rk  matches real issue Rk (a trailing * = right issue, but filed under a different axis than I would)
  DUP      same issue as another problem in the same list, split further (per call / per sub-point)
  OVER     claims more than the case file supports (e.g. asserts a condition is "supported" with no registry)
  FALSE    contradicted by the case file or the rules it cites
  UNSURE   cannot tell from the case file
usage: python problems_triage.py > problems_triage.md
"""
import collections, json
from pathlib import Path

HERE = Path(__file__).resolve().parent

REAL = {
    'R1': '保单·模型第二次输出违反系统提示词的输出契约（文字+JSON 混合、缺 claims、自填姓名/状态、自由文本含未引用的结论）｜程序可核，A/B1/B2/现行均有',
    'R2': '保单·交付附带假缺口并标 partial（模型 gaps=[]，交付变成「部分内容未能在本轮证据中对应」）｜程序可核',
    'R3': '两个 case·「本轮执行余量」不随用量更新（五次调用读数完全相同）｜程序逐字核对',
    'R4': 'D01·「按客户号升序」「我名下」在所有查询里丢失，全程未交代｜程序可核',
    'R5': 'D01·AMBIGUOUS 后换措辞重试（违反系统提示词「不得改写同一问题/重复调用已失败来源」）｜原文可核',
    'R6': 'D01·「确定选中后再查详情和保单状态」没有保留在任何结构化状态里（账本只存了澄清问题）｜可争议：原话仍在会话历史',
    'R7': 'D01·澄清/交付没说明真实原因，缺口说明笼统｜原文可核，程度低到中',
    'R8': '保单·当前状态的 as_of 为 null，答案却当作当前值陈述，没披露时点未知（系统提示词 L6）｜有规则依据，但 L6 写的是「金额按 as_of」，是否适用于状态有争议',
    'R9': 'D01·finalize 把 status 由 NEEDS_CLARIFICATION 变成 null｜事实成立，是否缺陷待查（两个 case 的 finalize 都输出 status:null，可能是既定形态）',
}

# (rep, case, axis, index) -> (label, reason)
L = {}


def put(rep, case, axis, labels):
    for i, (lab, why) in enumerate(labels):
        L[(rep, case, axis, i)] = (lab, why)


# ---- 保单 case ----
put(1, 'renyanlin', 'intent_understanding', [('FALSE', '两行险种记录并无冲突，工具说明只在「多行字段冲突」时禁止合成保单级结论'), ('REAL:R8*', '时点未知未披露成立，但这是输出内容问题，不是意图轴')])
put(2, 'renyanlin', 'intent_understanding', [('REAL:R8*', '同上，归错了轴')])
put(1, 'renyanlin', 'planning_routing', [('FALSE', '「本应走 to_capability」没有依据：输入里只有分支名，没有任何一条规则把这类问题指向它'), ('REAL:R2', '归因写成上游 finalize，合理')])
put(2, 'renyanlin', 'planning_routing', [('FALSE', '「本应走 to_direct」同样没有依据'), ('REAL:R1', '归因「未定位 agent/输出契约」合理'), ('OVER', '称「本轮证据」是被禁的内部词，但系统提示词列的是「工具返回/接口返回/EMPTY/BUDGET」，不含它')])
put(1, 'renyanlin', 'model_capability', [('FALSE', '「本应调用 run_policy_field_lookup」没有依据：工具说明明写已有完整保单号用 policy_detail'),
                                         ('REAL:R1', '文字+JSON 混合、缺 claims'), ('REAL:R1', '自填姓名/状态'),
                                         ('REAL:R1', '自由文本末尾的「有效」不在 facts 里，属契约问题的一个细点'), ('REAL:R1', '自由文本含未引用 fact 的结论')])
put(2, 'renyanlin', 'model_capability', [('FALSE', '同 B1：run_policy_field_lookup 无依据'), ('REAL:R1', '文字+JSON 混合'), ('REAL:R1', '缺 claims'), ('REAL:R1', '自填姓名/状态'), ('REAL:R1', '自由文本含未引用 fact 的结论')])
put(1, 'renyanlin', 'context_memory', [('REAL:R2', '')])
put(2, 'renyanlin', 'context_memory', [('REAL:R2', '')])
# ---- D01 ----
put(1, 'D01', 'intent_understanding', [('REAL:R6', ''), ('FALSE', '澄清是工具连续失败后触发的，不是意图轴「制造」的歧义')])
put(2, 'D01', 'intent_understanding', [('OVER', '这是结果（没拿到名单），不是表达缺陷'), ('REAL:R6', ''), ('REAL:R4', ''),
                                       ('OVER', '「客户号→clientNo 映射」没有规则依据'), ('REAL:R6', '「选中客户」指代没有被保留，是 R6 的一个侧面')])
put(1, 'D01', 'planning_routing', [('REAL:R4', '另含「姓平被改写」，那是 R5'), ('REAL:R5', ''), ('REAL:R7', ''), ('REAL:R6', '')])
put(2, 'D01', 'planning_routing', [('REAL:R4', ''), ('REAL:R5', ''), ('DUP', '排序未说明，是 R4/R7 的又一次拆分'),
                                   ('UNSURE', 'present_agentos 没有执行记录：案卷只到 finalize，无法判断是否本该有'), ('REAL:R7', '其中「按契约提供 claims」对一次澄清不成立')])
put(1, 'D01', 'tool_execution', [('OVER', '断言「对受支持条件返回 AMBIGUOUS」，但没有字段登记，无法知道「姓氏筛选」是否受支持'), ('DUP', '同上，tools/1'), ('DUP', '同上，tools/2'),
                                 ('FALSE', 'BUDGET 是预算守卫拦截（0.005 秒，未执行），不是工具故障')])
put(2, 'D01', 'tool_execution', [('FALSE', '同 B1：把预算守卫的拦截算成工具问题')])
put(1, 'D01', 'knowledge_data', [('OVER', '查询没有被执行，数据源无从说话，不应记为数据源问题'), ('REAL:R5', '归因写成上游 agent，处理正确')])
put(2, 'D01', 'knowledge_data', [('OVER', '同上'), ('REAL:R5', '上游：预算/循环控制，处理正确')])
put(1, 'D01', 'model_capability', [('REAL:R4', ''), ('REAL:R5', ''), ('REAL:R7', ''),
                                   ('UNSURE', '最后一次是 ask_clarify 工具调用，「answer_draft 首字段」的契约是否适用于它不清楚'),
                                   ('OVER', '选项 2 是给用户选的出路，不是系统自己去掉条件')])
put(2, 'D01', 'model_capability', [('REAL:R4', ''), ('DUP', '同上，第 2 次查询'), ('DUP', '同上，第 3 次查询'), ('REAL:R5', ''),
                                   ('UNSURE', '同 B1：契约是否适用于澄清调用'), ('REAL:R7', ''), ('DUP', 'R4 的又一次拆分'), ('DUP', 'R5 的又一次拆分')])
put(1, 'D01', 'context_memory', [('UNSURE', '「未携带全部历史配对」没说清楚会造成什么，自己也标了影响 no'), ('REAL:R7', '')])
put(2, 'D01', 'context_memory', [('REAL:R9', '')])

# which sources found which real issue (A and current pipeline are judged by me from their own outputs)
FOUND = {
    'A 手写': {'R1', 'R2', 'R3', 'R4', 'R5', 'R6~', 'R7'},
    '现行 21 单位流水线': {'R1', 'R4', 'R5', 'R6'},
}


# Same labelling rule applied to the other two sources, so the comparison is not one-sided.
# NOTE: the A list is graded by its own author (me) and is therefore the least trustworthy row.
A_PROBLEMS = [('保单', 'MP1', 'REAL:R1'), ('保单', 'CP1', 'REAL:R2'), ('保单', 'CP2', 'REAL:R3'),
              ('D01', 'IP1', 'REAL:R4'), ('D01', 'PP1', 'REAL:R5'), ('D01', 'MP2', 'REAL:R5'),
              ('D01', 'MP3', 'REAL:R7'), ('D01', 'CP3', 'REAL:R3')]
CURRENT_PROBLEMS = [('保单', 'model_capability: JSON 前多段文字、首字段不是 answer_draft', 'REAL:R1'),
                    ('保单', 'model_capability: 缺 claims、自填姓名/状态', 'REAL:R1'),
                    ('D01', 'intent: 遗漏归属范围与升序排序', 'REAL:R4'),
                    ('D01', 'intent: 遗漏「选中后查详情」', 'REAL:R6'),
                    ('D01', 'intent: 遗漏「选中后查保单状态」', 'REAL:R6'),
                    ('D01', 'planning: 连续改写重试直至预算拦截', 'REAL:R5'),
                    ('D01', 'context_memory: 「未交付名单」——这是上游结果，不是传递缺陷，且归因「未定位」', 'OVER')]


def run():
    b = {1: collections.Counter(), 2: collections.Counter()}
    found = {1: set(), 2: set()}
    rows = []
    for (rep, case, axis, i), (lab, why) in sorted(L.items()):
        key = lab.split(':')[0] if lab.startswith('REAL') else lab
        b[rep][key] += 1
        if lab.startswith('REAL'):
            found[rep].add(lab.split(':')[1].rstrip('*'))
        rows.append((rep, case, axis, i, lab, why))
    FOUND['B1 盲写'] = found[1]
    FOUND['B2 盲写'] = found[2]
    print('# 盲写两遍所报问题的归类（我的判断，逐条可推翻）\n')
    print('## 真实问题清单（R1–R9）\n')
    for k, v in REAL.items():
        print(f'- **{k}** {v}')
    print('\n## 归类计数\n')
    print('| 来源 | 总数 | 命中真实问题 | 重复拆分 | 过度断言 | 被案卷/规则反驳 | 无法判断 |')
    print('|---|---|---|---|---|---|---|')
    for rep in (1, 2):
        c = b[rep]
        print(f"| B{rep} 盲写 | {sum(c.values())} | {c['REAL']} | {c['DUP']} | {c['OVER']} | {c['FALSE']} | {c['UNSURE']} |")
    print('\n## 谁找到了哪些真实问题\n')
    print('| 真实问题 | A 手写 | B1 盲写 | B2 盲写 | 现行 21 单位流水线 |')
    print('|---|---|---|---|---|')
    for k in REAL:
        def mark(src):
            s = FOUND[src]
            return '✓' if k in s else ('～' if k + '~' in s else '—')
        print(f"| {k} | {mark('A 手写')} | {mark('B1 盲写')} | {mark('B2 盲写')} | {mark('现行 21 单位流水线')} |")
    print('\n## 同一规则下 A 与现行流水线的问题归类\n')
    print('| 来源 | 问题记录数 | 命中真实问题 | 过度/错误 | 备注 |')
    print('|---|---|---|---|---|')
    ar = sum(l.startswith('REAL') for _, _, l in A_PROBLEMS)
    cr = sum(l.startswith('REAL') for _, _, l in CURRENT_PROBLEMS)
    print(f'| A 手写 | {len(A_PROBLEMS)} | {ar} | {len(A_PROBLEMS) - ar} | **我评我自己**，最不可信；另有 1 个待查项（IQ1）未计入 |')
    print(f'| 现行 21 单位流水线 | {len(CURRENT_PROBLEMS)} | {cr} | {len(CURRENT_PROBLEMS) - cr} | 同一问题的不同子点各记一条，与 B 的口径一致 |')
    print('\n## 逐条明细\n')
    print('| 轮 | case | 轴 | # | 归类 | 理由 |')
    print('|---|---|---|---|---|---|')
    for rep, case, axis, i, lab, why in rows:
        print(f'| B{rep} | {case} | {axis} | {i} | {lab} | {why} |')


if __name__ == '__main__':
    run()
