"""协议层约束机制单元测试

验证：
1. 协议层基类能被正常继承
2. 子类覆盖禁止方法时会抛 TypeError
3. 子类实现扩展点能正常工作
"""
from __future__ import annotations

import pytest

from impl.core.judge_protocol import _JudgeProtocol, ProjectJudge
from impl.core.live_protocol import _LiveProtocol, ProjectLive
from impl.core.attribute_protocol import _AttributeProtocol, ProjectAttribute
from impl.core.tools_protocol import _ToolsProtocol, ProjectTools
from impl.core.mock_protocol import _MockProtocol, ProjectMock


class TestJudgeProtocol:
    """Judge 协议层约束测试"""

    def test_project_judge_can_be_subclassed(self):
        """项目可以正常继承 ProjectJudge 并实现扩展点"""
        class TestJudge(ProjectJudge):
            def build_context(self, trace):
                return {"test": "context"}

        judge = TestJudge(spec=None)
        assert judge.build_context(None) == {"test": "context"}

    def test_override_judge_trace_raises_error(self):
        """子类覆盖 judge_trace 模板方法时抛 TypeError"""
        with pytest.raises(TypeError, match="judge_trace"):
            class BadJudge(ProjectJudge):
                def judge_trace(self, trace, expected_intent=None):
                    return "hacked"

                def build_context(self, trace):
                    return {}

    def test_override_run_llm_judge_raises_error(self):
        """子类覆盖 _run_llm_judge 内部方法时抛 TypeError"""
        with pytest.raises(TypeError, match="_run_llm_judge"):
            class BadJudge2(ProjectJudge):
                def _run_llm_judge(self, trace, context, expected_intent):
                    return "hacked"

                def build_context(self, trace):
                    return {}

    def test_normalize_result_can_be_overridden(self):
        """normalize_result 是扩展点，可以被覆盖"""
        class TestJudge2(ProjectJudge):
            def build_context(self, trace):
                return {}

            def normalize_result(self, trace, result):
                return "custom_normalized"

        judge = TestJudge2(spec=None)
        assert judge.normalize_result(None, None) == "custom_normalized"


class TestLiveProtocol:
    """Live 协议层约束测试"""

    def test_project_live_can_be_subclassed(self):
        """项目继承 ProjectLive 时需通过中间基类指定 real/provided 模式"""
        # ProjectLive 自身不强制 deliver_real/deliver_provided
        # 项目应继承 RealServiceLive 或 ProvidedOutputLive
        from impl.core.live_protocol import RealServiceLive, ProvidedOutputLive
        from impl.core.live_transport import LiveTransport

        class TestRealLive(RealServiceLive):
            def deliver_real(self, request, transport):
                return transport

            def extract_output(self, raw_response):
                return {"test": "response"}

        live = TestRealLive(spec=None)
        transport = LiveTransport()
        assert live.deliver_real(None, transport) is transport
        # build_request 已删除（trace.md 第十二节），意图计算由 trace 层调 _resolve_intent
        # 不再测试 build_request 默认实现

        class TestProvidedLive(ProvidedOutputLive):
            def deliver_provided(self, request):
                return {"test": "provided"}

        live2 = TestProvidedLive(spec=None)
        assert live2.deliver_provided(None) == {"test": "provided"}

    def test_override_deliver_raises_error(self):
        """deliver 模板方法已删除（trace.md 第十二节），不再测试覆盖禁止"""
        pass

    def test_override_run_provided_raises_error(self):
        """子类覆盖 _run_provided 内部方法时抛 TypeError"""
        from impl.core.live_protocol import RealServiceLive
        with pytest.raises(TypeError, match="_run_provided"):
            class BadLive2(RealServiceLive):
                def _run_provided(self, case, request):
                    return "hacked"

                def deliver_real(self, request, transport):
                    return transport

                def extract_output(self, raw_response):
                    return {}

    def test_extract_output_can_be_overridden(self):
        """extract_output 是扩展点，可以被覆盖"""
        from impl.core.live_protocol import RealServiceLive
        class TestLive2(RealServiceLive):
            def deliver_real(self, request, transport):
                return transport

            def extract_output(self, raw_response):
                return {"extracted": True}

        live = TestLive2(spec=None)
        assert live.extract_output([]) == {"extracted": True}

    def test_real_service_live_requires_deliver_real(self):
        """RealServiceLive 必须实现 deliver_real，未实现时无法实例化"""
        from impl.core.live_protocol import RealServiceLive
        with pytest.raises(TypeError, match="deliver_real|abstract"):
            class BadRealLive(RealServiceLive):
                pass
            BadRealLive(spec=None)

    def test_provided_output_live_requires_deliver_provided(self):
        """ProvidedOutputLive 必须实现 deliver_provided，未实现时无法实例化"""
        from impl.core.live_protocol import ProvidedOutputLive
        with pytest.raises(TypeError, match="deliver_provided|abstract"):
            class BadProvidedLive(ProvidedOutputLive):
                pass
            BadProvidedLive(spec=None)

    def test_real_service_live_deliver_provided_raises_by_default(self):
        """RealServiceLive 的 deliver_provided 默认 raise NotImplementedError"""
        from impl.core.live_protocol import RealServiceLive
        class TestRealLive(RealServiceLive):
            def deliver_real(self, request, transport):
                return transport

            def extract_output(self, raw_response):
                return {}
        live = TestRealLive(spec=None)
        with pytest.raises(NotImplementedError, match="deliver_provided"):
            live.deliver_provided(None)

    def test_provided_output_live_deliver_real_raises_by_default(self):
        """ProvidedOutputLive 的 deliver_real 默认 raise NotImplementedError"""
        from impl.core.live_protocol import ProvidedOutputLive
        class TestProvidedLive(ProvidedOutputLive):
            def deliver_provided(self, request):
                return {}
        live = TestProvidedLive(spec=None)
        with pytest.raises(NotImplementedError, match="deliver_real"):
            live.deliver_real(None, None)


class TestAttributeProtocol:
    """Attribute 协议层约束测试"""

    def test_project_attribute_can_be_subclassed(self):
        """项目可以正常继承 ProjectAttribute 并实现扩展点"""
        class TestAttribute(ProjectAttribute):
            def build_context(self, trace, judge_result):
                return {"test": "context"}

        attr = TestAttribute(spec=None)
        assert attr.build_context(None, None) == {"test": "context"}

    def test_override_attribute_failure_raises_error(self):
        """子类覆盖 attribute_failure 模板方法时抛 TypeError"""
        with pytest.raises(TypeError, match="attribute_failure"):
            class BadAttribute(ProjectAttribute):
                def attribute_failure(self, trace, judge_result):
                    return "hacked"

                def build_context(self, trace, judge_result):
                    return {}

    def test_override_run_probes_raises_error(self):
        """子类覆盖 _run_probes 内部方法时抛 TypeError"""
        with pytest.raises(TypeError, match="_run_probes"):
            class BadAttribute2(ProjectAttribute):
                def _run_probes(self, trace, judge_result):
                    return ["hacked"]

                def build_context(self, trace, judge_result):
                    return {}

    def test_probes_can_be_overridden(self):
        """probes 是扩展点，可以被覆盖"""
        class TestAttribute2(ProjectAttribute):
            def build_context(self, trace, judge_result):
                return {}

            def probes(self):
                def probe_fn(trace, judge_result):
                    return [{"probe": "result"}]
                return probe_fn

        attr = TestAttribute2(spec=None)
        probe_fn = attr.probes()
        assert probe_fn(None, None) == [{"probe": "result"}]


class TestToolsProtocol:
    """Tools 协议层约束测试"""

    def test_project_tools_can_be_subclassed(self):
        """项目可以正常继承 ProjectTools"""
        class TestTools(ProjectTools):
            pass

        tools = TestTools(spec=None)
        assert tools.verifiable_tools() == []

    def test_override_all_tools_raises_error(self):
        """子类覆盖 all_tools 模板方法时抛 TypeError"""
        with pytest.raises(TypeError, match="all_tools"):
            class BadTools(ProjectTools):
                def all_tools(self):
                    return "hacked"

    def test_verifiable_tools_can_be_overridden(self):
        """verifiable_tools 是扩展点，可以被覆盖"""
        class TestTools2(ProjectTools):
            def verifiable_tools(self):
                return [{"tool": "test"}]

        tools = TestTools2(spec=None)
        assert tools.verifiable_tools() == [{"tool": "test"}]

    def test_runtime_checks_can_be_overridden(self):
        """runtime_checks 是扩展点，可以被覆盖"""
        class TestTools3(ProjectTools):
            def runtime_checks(self, runtime_values, context=None):
                return {"check": "passed"}

        tools = TestTools3(spec=None)
        assert tools.runtime_checks({}) == {"check": "passed"}


class TestMockProtocol:
    """Mock 协议层约束测试"""

    def test_project_mock_can_be_subclassed(self):
        """项目可以正常继承 ProjectMock 并实现扩展点"""
        class TestMock(ProjectMock):
            def build_user_intent(self, scenario):
                return {"query": "test", "expected_intent": "test_intent"}

            def intent_labels(self):
                return ["intent1", "intent2"]

            def next_turn(self, case, previous_turns, live_feedback):
                return {"query": "next"}

        mock = TestMock(spec=None)
        assert mock.intent_labels() == ["intent1", "intent2"]
        assert mock.build_user_intent("test") == {"query": "test", "expected_intent": "test_intent"}
        # scenarios 有默认实现（从 live_schema 取，spec=None 返回空）
        assert mock.scenarios() == []

    def test_override_generate_mock_case_raises_error(self):
        """子类覆盖 generate_mock_case 模板方法时抛 TypeError"""
        with pytest.raises(TypeError, match="generate_mock_case"):
            class BadMock(ProjectMock):
                def generate_mock_case(self, scenario=None, intent=None, **kwargs):
                    return "hacked"

                def build_user_intent(self, scenario):
                    return {}

    def test_build_user_intent_must_be_implemented(self):
        """build_user_intent 是必须实现的扩展点"""
        with pytest.raises(TypeError, match="build_user_intent|abstract"):
            class BadMock2(ProjectMock):
                pass
            BadMock2(spec=None)

    def test_multi_turn_mock_must_implement_intent_inference(self):
        from impl.core.mock_protocol import MultiTurnInteractiveMock

        with pytest.raises(TypeError, match="infer_user_intent|abstract"):
            class MissingInference(MultiTurnInteractiveMock, ProjectMock):
                def build_user_intent(self, scenario):
                    return {}

                def decide_next_action(self, intent, accumulated_output):
                    return None

                def build_next_request(self, intent, accumulated_output=None):
                    return {}

                def safety_max_turns(self):
                    return 12

            MissingInference(spec=None)

    def test_intent_labels_optional(self):
        """intent_labels 是可选扩展点，不实现时返回空列表"""
        class TestMock(ProjectMock):
            def build_user_intent(self, scenario):
                return {}

        mock = TestMock(spec=None)
        assert mock.intent_labels() == []  # 默认返回空列表


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
