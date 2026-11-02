"""标准答案草稿：按文档逐条标主轴三态，写 gold.json。依据缩写见 GOLD_BASIS；ask=True 的是口径拿不准、需用户定的。"""
import json
from pathlib import Path

HERE = Path(__file__).parent
GOLD_BASIS = {
    'F': 'fulfilled.md §2.1：用户要的结果给到了，核心事实与信息源一致',
    'NF-wrong': 'fulfilled.md §2.2 改错值；D18：refuted 的断言视为事实错误，相关期望 not_fulfilled',
    'NF-missing': 'fulfilled.md §2.2 该出结果没出、§4.1 如实拒绝≠办成、§4.4（10-19 用户口径：原因归轴2，主轴照判没办成）',
    'NE-core': 'D18（fulfilled.md §2.3 事实核实不了）：结论依赖的核心断言 unverifiable',
}
G = {}


def gold(ids, label, why, basis, ask=False, accept=()):
    for i in ids.split():
        G[i] = {'gold': label, 'why': why, 'basis': GOLD_BASIS[basis], 'ask': ask, 'accept': [label, *accept]}


# —— 合成：条款 / 员工手册 / 短答 ——
gold('F-annual-ok F-hes-ok hr-annual-ok hr-probation-ok hr-resign-ok clause-verified-kn-hesitation clause-multi-ax',
     'fulfilled', '核心数值与知识库一致', 'F')
gold('F-c8 F-hes-wrong hr-annual-wrong hr-probation-wrong hr-resign-wrong', 'not_fulfilled', '核心数值与知识库不一致', 'NF-wrong')
gold('clause-refuted-xx-hesitation-stale', 'not_fulfilled',
     '问题里贴的条款写二十日，知识库是十五日；场景配置"条款事实以知识库为准"，回答照贴的条款答二十天，与知识库不符', 'NF-wrong')
gold('hr-annual-side', 'not_fulfilled',
     '核心"十天"对；附带"没休完年底折现"与手册（逾期作废、不予折算）相反。场景判准"编造条款算没办成"。旧实验标的是 fulfilled，用户 10-20 定：附带说法错的也挡', 'NF-wrong')
gold('hr-probation-side hr-resign-side', 'not_evaluable',
     '核心对；附带说法（每月交工作总结 / 发邮件即书面通知）手册里查不到。用户 10-20 定：附带说法查不到的也挡（旧实验标 fulfilled）', 'NE-core')
gold('hr-housing-core hr-petleave-core clause-unverifiable-kn-cashvalue F-c9', 'not_evaluable',
     '核心说法在知识库里查不到依据（unverifiable）', 'NE-core')
gold('clause-noclaim-opinion', 'fulfilled', '问的是适不适合、要求不引用数字；回答给了看法、无事实断言', 'F')
# —— 单位缺失 ——
gold('unit-policy-present', 'fulfilled', '数值 1089.1 与保单详情一致；"元"信息源没给（unverifiable），不挡核心（C1 门槛）', 'F')
gold('unit-policy-absent', 'not_fulfilled',
     '保单 P260922000099999 不存在（查询 EMPTY），回答编了一个保费数；旧实验标 not_evaluable，用户 10-20 定为没办成', 'NF-wrong')
# —— 保险：答对的 ——
gold('mcp-bizno mcp-bizno-1018 mcp-bizno-1020 agno-bizno-1020 langfuse-bizno-1020', 'fulfilled', '何承琪/女/63/离婚/手机号与客户查询一致', 'F')
gold('mcp-fuyunping-policies-1018', 'fulfilled', '两张保单的产品、状态、投保日期与查询一致', 'F')
gold('mcp-main-A02-yuxinya-status mcp-main-A02-yuxinya-status-1020 agno-main-A02-yuxinya-status-1020 langfuse-main-A02-yuxinya-status-1020',
     'fulfilled', '2 张保单（9116 e生保、9117 安佑福惠享版）均交费有效，与查询一致', 'F')
gold('agno-main-C08-two-customers-parallel-1020', 'fulfilled',
     '保单分组列对了、解释了投保人；附带写错"客户中心ID以 C92200004628 关联"（那是寿险客户号）。用户 10-25 定：要的都给了算做成，附带说错归模型能力有问题（不再按 10-20"附带说法错的也挡"）', 'F')
gold('langfuse-main-C08-two-customers-parallel-1020', 'fulfilled',
     '两人各 2 张保单分组列出、与查询一致，解释了投保人；附带"续期保费合计 108.3 + 62.5 = 170.8"，数据说明写险种行不得当保单合计——用户 10-20 定办成、说不清都算对', 'F', accept=('not_evaluable',))
gold('mcp-main-C08-two-customers-parallel-1020',
     'fulfilled', '两人各 2 张保单分组列出、与查询一致，解释了投保人', 'F')
gold('mcp-main-C08-two-customers-parallel', 'fulfilled',
     '核心同上；开头漏出一句英文思考，附带"姓名字段为加密值"被真实性判 refuted（policy_search 里确是密文、policy_detail 是明文），与用户要的无关（用户 10-20 定办成）', 'F')
gold('mcp-main-D16-near-name-split mcp-main-D16-near-name-split-1020 agno-main-D16-near-name-split-1020 langfuse-main-D16-near-name-split-1020',
     'fulfilled', '确认是两位客户、分别给出档案，字段与客户详情一致', 'F')
gold('mcp-smoke-policy-detail-renyanlin mcp-smoke-policy-detail-renyanlin-1020 agno-smoke-policy-detail-renyanlin-1020 langfuse-smoke-policy-detail-renyanlin-1020',
     'fulfilled', '投保人、被保人都是任言琳，交费有效，与保单详情一致', 'F')
gold('mcp-main-G01-short-answer mcp-main-G01-short-answer-1020 agno-main-G01-short-answer-1020 langfuse-main-G01-short-answer-1020',
     'fulfilled', '1089.1 与保单详情一致；"元"信息源没给。用户说"只回答金额"，回答是整句——用户 10-20 定：按核心结果判办成；单位"元"查不到也不挡（C1 值与单位分开核）', 'F')
# —— 保险：没给出用户要的 ——
gold('mcp-smoke-neg-unknown-policy', 'not_fulfilled', '用户要被保人，没给出；保单确不存在是成因，归轴2（10-19 用户口径）', 'NF-missing')
gold('mcp-main-B02-policy-plus-waiting mcp-main-B02-policy-plus-waiting-1019b agno-main-B02-policy-plus-waiting-1020 langfuse-main-B02-policy-plus-waiting-1020',
     'not_fulfilled', '用户要的等待期没给出（信息源没有 1836 条款）；1019b 还说"无法确认是否购买"而数据里有；langfuse 版把两张保单号写反了', 'NF-missing')
gold('mcp-main-E01-ref-product-knowledge mcp-main-E01-ref-product-knowledge-1020 agno-main-E01-ref-product-knowledge-1020 langfuse-main-E01-ref-product-knowledge-1020',
     'not_fulfilled', '第 3 轮要安佑福的等待期和免责，没给出', 'NF-missing')
gold('mcp-main-F01-name-correction mcp-main-F01-name-correction-1019b agno-main-F01-name-correction-1020 langfuse-main-F01-name-correction-1020',
     'not_fulfilled', '改名后要余昕雅的累计已交保费 + 安佑福免责：免责都没给出；旧答案还说"未返回累计已交保费"（数据里有），agno 版保费也没给', 'NF-missing')

ids = {json.loads(f.read_text())['id'] for f in (HERE / 'cases').glob('*.json')}
assert set(G) == ids, (sorted(ids - set(G)), sorted(set(G) - ids))
(HERE / 'gold.json').write_text(json.dumps(G, ensure_ascii=False, indent=1))
print(len(G), {k: sum(v['gold'] == k for v in G.values()) for k in ('fulfilled', 'not_fulfilled', 'not_evaluable')}, 'ask', sum(v['ask'] for v in G.values()))
