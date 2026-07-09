❯ 比如说，正式版的attribute怎么传过去的，draft的attribute怎么传过去的？                                                                            

⏺ 是通过 ProjectSpec 传进去的，具体链路是这样的。

正式版路径：

pipeline.attribute(project_id, trace, judge_result)
→ spec = load_project(project_id)
→ project_attribute = load_project_attribute(spec)
→ load_project_attribute(spec) 发现 spec.attribute_draft 没有 enabled
→ 加载 impl/projects/client_search/attribute.py
→ 调用 project_attribute.attribute_failure(spec, adapter, trace, judge_result)

也就是正式版传进去的是这个模块：

impl/projects/client_search/attribute.py

它的入口函数是：

attribute_failure(spec, adapter, trace, judge_result)

Draft 路径：

pipeline.attribute(project_id, trace, judge_result)
→ spec = load_project(project_id)
→ project_attribute = load_project_attribute(spec)
→ load_project_attribute(spec) 发现 spec.attribute_draft.enabled == true
→ 读取 spec.attribute_draft.module，例如 draft/attribute.py
→ 加载 impl/projects/client_search/draft/attribute.py
→ 调用 project_attribute.attribute_failure(spec, adapter, trace, judge_result)

也就是 draft 版传进去的是这个模块：

impl/projects/client_search/draft/attribute.py

它同样必须暴露：

attribute_failure(spec, adapter, trace, judge_result)

所以“正式版 attribute / draft attribute 怎么传过去”的答案是：

- 不是把某个函数对象从外面手动传给 pipeline。
- 而是 pipeline.attribute() 根据 ProjectSpec.attribute_draft 调 load_project_attribute(spec)。
- loader 动态 import 对应模块。
- import 后拿到模块对象 project_attribute。
- pipeline 调用模块上的统一入口 attribute_failure(...)。

核心判断类似：

def load_project_attribute(spec):
    draft_filename = _safe_draft_attribute_filename(spec)
    if draft_filename:
        return _load_project_module(spec, draft_filename, "attribute_draft")
    return _load_project_module(spec, "attribute.py", "attribute")

然后：

project_attribute = load_project_attribute(spec)

if project_attribute is not None and hasattr(project_attribute, "attribute_failure"):
    result = project_attribute.attribute_failure(spec, adapter, trace, judge_result)

所以两者的差异只在 loader 加载哪个 Python 文件：

formal: impl/projects/client_search/attribute.py
draft:  impl/projects/client_search/draft/attribute.py

进入 pipeline 之后，调用方式完全一致。