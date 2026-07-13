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





---------------

我需要judge也有judge机制，你看看是要在搞一个skill，还是混合到当前的skiil里面 你先想想，别动手
我希望draft这种东西，还是能复用一下，但是我也觉得judge 和attr做两套skill好像好一点，怎么能做好呢

 或者这样。skill改名字为draft，然后SKILL.md写draft的机制，然后内置构建attribute和judge两个子目录，公共的部分就在公共的目录里面写，attr/judge特异的
  部分就在对应的地方写，然后把那些相关的reference啥的也都搬进去，公共层写一个模版套架的references，然后attr和judge相应的reference从公共层的reference保持结构
  上一致，有一些扩展性的东西，并且把attr/judge的定位需求啥的也写在attr/judge的子目录里面。你先构思一下