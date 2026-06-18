import unittest
from unittest.mock import Mock, patch

from impl.core.attribute import attribute_failure
from impl.core.judge import judge_trace
from impl.core.knowledge_base import DEFAULT_RETRIEVAL_TOP_K, ProjectKnowledgeBase, load_knowledge_base
from impl.core.llm_client import LlmClient, project_llm_client
from impl.core.schema import JudgeResult, ProjectSpec, RunTrace


class LlmClientAgnoTest(unittest.TestCase):
    def test_complete_json_uses_agno_agent_and_preserves_usage(self):
        run_output = Mock()
        run_output.content = '{"verdict":"correct"}'
        run_output.raw_response = {"usage": {"prompt_tokens": 11, "completion_tokens": 7}}

        agent = Mock()
        agent.run.return_value = run_output

        with patch("impl.core.llm_client.DeepSeek") as deepseek, patch("impl.core.llm_client.Agent", return_value=agent) as agent_cls:
            result = LlmClient(api_key="key").complete_json("system", "user")

        deepseek.assert_called_once()
        agent_cls.assert_called_once()
        agent.run.assert_called_once_with("user")
        self.assertEqual(result["verdict"], "correct")
        self.assertEqual(result["raw_model_response"]["usage"]["prompt_tokens"], 11)

    def test_complete_json_normalizes_chat_completions_base_url_for_agno(self):
        agent = Mock()
        agent.run.return_value = Mock(content='{"ok":true}', raw_response={})

        with patch("impl.core.llm_client.DeepSeek") as deepseek, patch("impl.core.llm_client.Agent", return_value=agent):
            LlmClient(api_key="key", base_url="https://api.deepseek.com/v1/chat/completions").complete_json("system", "user")

        self.assertEqual(deepseek.call_args.kwargs["base_url"], "https://api.deepseek.com")

    def test_complete_json_passes_memory_db_and_knowledge_retriever_to_agno_agent(self):
        memory_manager = Mock()
        memory_db = Mock()
        knowledge = Mock()
        knowledge_retriever = Mock()
        agent = Mock()
        agent.run.return_value = Mock(content='{"ok":true}', raw_response={})

        with patch("impl.core.llm_client.DeepSeek"), patch("impl.core.llm_client.Agent", return_value=agent) as agent_cls:
            result = LlmClient(
                api_key="key",
                memory_manager=memory_manager,
                memory_db=memory_db,
                knowledge=knowledge,
                knowledge_retriever=knowledge_retriever,
                user_id="demo-user",
                session_id="demo-session",
            ).complete_json("system", "user")

        agent_kwargs = agent_cls.call_args.kwargs
        self.assertIs(agent_kwargs["memory_manager"], memory_manager)
        self.assertIs(agent_kwargs["db"], memory_db)
        self.assertIs(agent_kwargs["knowledge"], knowledge)
        self.assertIs(agent_kwargs["knowledge_retriever"], knowledge_retriever)
        self.assertEqual(agent_kwargs["user_id"], "demo-user")
        self.assertEqual(agent_kwargs["session_id"], "demo-session")
        self.assertTrue(agent_kwargs["enable_user_memories"])
        self.assertTrue(agent_kwargs["add_memories_to_context"])
        self.assertTrue(agent_kwargs["add_knowledge_to_context"])
        self.assertTrue(result["ok"])

    def test_complete_json_passes_memory_and_knowledge_to_agno_agent(self):
        memory_manager = Mock()
        knowledge = Mock()
        agent = Mock()
        agent.run.return_value = Mock(content='{"ok":true}', raw_response={})

        with patch("impl.core.llm_client.DeepSeek"), patch("impl.core.llm_client.Agent", return_value=agent) as agent_cls:
            result = LlmClient(
                api_key="key",
                memory_manager=memory_manager,
                knowledge=knowledge,
                user_id="demo-user",
                session_id="demo-session",
            ).complete_json("system", "user")

        agent_kwargs = agent_cls.call_args.kwargs
        self.assertIs(agent_kwargs["memory_manager"], memory_manager)
        self.assertIs(agent_kwargs["knowledge"], knowledge)
        self.assertEqual(agent_kwargs["user_id"], "demo-user")
        self.assertEqual(agent_kwargs["session_id"], "demo-session")
        self.assertTrue(agent_kwargs["enable_user_memories"])
        self.assertTrue(agent_kwargs["add_memories_to_context"])
        self.assertTrue(agent_kwargs["add_knowledge_to_context"])
        self.assertTrue(result["ok"])

    def test_project_llm_client_builds_project_scoped_memory_and_knowledge(self):
        knowledge = Mock()
        spec = ProjectSpec(project_id="demo", name="Demo")

        with patch("impl.core.llm_client.JsonDb") as json_db, patch("impl.core.llm_client.MemoryManager") as memory_manager:
            client = project_llm_client(spec, role="judge", knowledge=knowledge)

        json_db.assert_called_once()
        self.assertIn("agno_memory.json", json_db.call_args.kwargs["db_path"])
        memory_manager.assert_called_once_with(db=json_db.return_value)
        self.assertIs(client.memory_manager, memory_manager.return_value)
        self.assertIs(client.memory_db, json_db.return_value)
        self.assertIs(client.knowledge, knowledge)
        self.assertEqual(client.user_id, "demo")
        self.assertEqual(client.session_id, "demo:judge")

    def test_complete_json_returns_structured_error_when_agno_agent_fails(self):
        agent = Mock()
        agent.run.side_effect = RuntimeError("boom")

        with patch("impl.core.llm_client.DeepSeek"), patch("impl.core.llm_client.Agent", return_value=agent):
            result = LlmClient(api_key="key").complete_json("system", "user")

        self.assertEqual(result["error"], "llm_request_failed")
        self.assertIn("boom", result["raw_text"])


class KnowledgeRetrievalTest(unittest.TestCase):
    def test_project_knowledge_builds_project_directory_and_indexes_documents(self):
        spec = ProjectSpec(
            project_id="demo",
            name="Demo",
            root="/tmp/demo-project",
            documents={
                "evaluation": "evaluation.md",
                "source_config": "config.yaml",
                "source_field_definitions": "fields.yaml",
            },
        )
        kb = ProjectKnowledgeBase("demo")
        kb._read_text = Mock(side_effect=lambda path: "intents:\n- field: age\n  operator: GT\n  description: customer age" if str(path).endswith("fields.yaml") else f"content for {path}")
        kb._path_exists = Mock(return_value=True)
        kb.vector_db.upsert = Mock()
        kb.vector_db.create = Mock()

        kb.build_from_project(spec)

        self.assertEqual(kb.storage_dir.as_posix(), str(ProjectKnowledgeBase.KNOWLEDGE_ROOT / "demo"))
        documents = kb.vector_db.upsert.call_args.args[1]
        document_names = {document.name for document in documents}
        self.assertIn("field:age", document_names)
        self.assertIn("project_doc:evaluation", document_names)
        self.assertIn("project_doc:source_config", document_names)

    def test_load_knowledge_base_accepts_project_spec_and_caches_project_knowledge(self):
        spec = ProjectSpec(project_id="demo-cache", name="Demo", root="/tmp/demo-project", documents={})

        with patch.object(ProjectKnowledgeBase, "build_from_project") as build_from_project:
            first = load_knowledge_base(spec)
            second = load_knowledge_base(spec)

        self.assertIs(first, second)
        build_from_project.assert_called_once_with(spec)

    def test_default_retrieval_top_k_keeps_agent_context_small(self):
        self.assertLessEqual(DEFAULT_RETRIEVAL_TOP_K, 8)

    def test_to_context_uses_small_default_retrieval_limit(self):
        kb = ProjectKnowledgeBase("demo")
        kb.search = Mock(return_value=[])

        kb.to_context("query")

        kb.search.assert_called_once_with("query", DEFAULT_RETRIEVAL_TOP_K)


class ProjectMemoryIsolationTest(unittest.TestCase):
    def test_different_projects_use_separate_memory_databases(self):
        spec_a = ProjectSpec(project_id="project_a", name="Project A")
        spec_b = ProjectSpec(project_id="project_b", name="Project B")

        with patch("impl.core.llm_client.JsonDb") as json_db_mock:
            client_a = project_llm_client(spec_a, role="judge")
            client_b = project_llm_client(spec_b, role="judge")

        calls = json_db_mock.call_args_list
        self.assertEqual(len(calls), 2)
        path_a = calls[0].kwargs["db_path"]
        path_b = calls[1].kwargs["db_path"]
        self.assertIn("project_a", path_a)
        self.assertIn("project_b", path_b)
        self.assertNotEqual(path_a, path_b)


class RuntimeFallbackTest(unittest.TestCase):
    def test_judge_trace_passes_project_knowledge_to_project_client(self):
        spec = ProjectSpec(project_id="demo", name="Demo", documents={"source_field_definitions": "fields.yaml"})
        trace = RunTrace(
            trace_id="t1",
            project_id="demo",
            input={"query": "find clients"},
            normalized_request={"query": "find clients"},
            extracted_output={"filters": []},
        )
        client = Mock()
        client.complete_json.return_value = {"error": "llm_request_failed", "raw_text": "boom"}
        knowledge = Mock()
        knowledge.to_context.return_value = "field context"

        with patch("impl.core.judge.load_knowledge_base", return_value=knowledge), patch("impl.core.judge.project_llm_client", return_value=client) as client_factory:
            judge_trace(spec, trace, llm=None)

        client_factory.assert_called_once()
        self.assertIs(client_factory.call_args.kwargs["knowledge"], knowledge)

    def test_attribute_failure_uses_existing_project_knowledge_for_project_client(self):
        spec = ProjectSpec(project_id="demo", name="Demo")
        trace = RunTrace(
            trace_id="t1",
            project_id="demo",
            input={"case_id": "c1", "query": "find clients"},
            normalized_request={"query": "find clients"},
            extracted_output={"filters": []},
        )
        judge = JudgeResult(
            trace_id="t1",
            project_id="demo",
            verdict="incorrect",
            fulfillment_assessments=[{"expectation_id": "e1", "status": "not_fulfilled"}],
            overall_fulfillment={"status": "not_fulfilled"},
        )
        client = Mock()
        client.complete_json.return_value = {"error": "llm_request_failed", "raw_text": "boom"}
        knowledge = Mock()

        with patch("impl.core.attribute.get_knowledge_base", return_value=knowledge), patch("impl.core.attribute.project_llm_client", return_value=client) as client_factory:
            attribute_failure(spec, trace, judge, llm=None)

        client_factory.assert_called_once()
        self.assertIs(client_factory.call_args.kwargs["knowledge"], knowledge)

    def test_judge_trace_uses_project_scoped_client_by_default(self):
        spec = ProjectSpec(project_id="demo", name="Demo")
        trace = RunTrace(
            trace_id="t1",
            project_id="demo",
            input={"query": "find clients"},
            normalized_request={"query": "find clients"},
            extracted_output={"filters": []},
        )
        client = Mock()
        client.complete_json.return_value = {"error": "llm_request_failed", "raw_text": "boom"}

        with patch("impl.core.judge.project_llm_client", return_value=client) as client_factory:
            judge_trace(spec, trace, llm=None)

        client_factory.assert_called_once()
        self.assertEqual(client_factory.call_args.args[0], spec)
        self.assertEqual(client_factory.call_args.kwargs["role"], "judge")

    def test_attribute_failure_uses_project_scoped_client_by_default(self):
        spec = ProjectSpec(project_id="demo", name="Demo")
        trace = RunTrace(
            trace_id="t1",
            project_id="demo",
            input={"case_id": "c1", "query": "find clients"},
            normalized_request={"query": "find clients"},
            extracted_output={"filters": []},
        )
        judge = JudgeResult(
            trace_id="t1",
            project_id="demo",
            verdict="incorrect",
            fulfillment_assessments=[{"expectation_id": "e1", "status": "not_fulfilled"}],
            overall_fulfillment={"status": "not_fulfilled"},
        )
        client = Mock()
        client.complete_json.return_value = {"error": "llm_request_failed", "raw_text": "boom"}

        with patch("impl.core.attribute.project_llm_client", return_value=client) as client_factory:
            attribute_failure(spec, trace, judge, llm=None)

        client_factory.assert_called_once()
        self.assertEqual(client_factory.call_args.args[0], spec)
        self.assertEqual(client_factory.call_args.kwargs["role"], "attribute")

    def test_judge_trace_returns_structured_fallback_when_agent_fails(self):
        spec = ProjectSpec(project_id="demo", name="Demo")
        trace = RunTrace(
            trace_id="t1",
            project_id="demo",
            input={"query": "find clients"},
            normalized_request={"query": "find clients"},
            extracted_output={"filters": []},
        )
        llm = Mock()
        llm.complete_json.return_value = {"error": "llm_request_failed", "raw_text": "boom"}

        result = judge_trace(spec, trace, llm=llm)

        self.assertEqual(result.verdict, "uncertain")
        self.assertEqual(result.judge_method, "llm_call_failed")
        self.assertIn("llm_call_failed", result.quality_flags)
        self.assertEqual(result.raw_model_output["error"], "llm_request_failed")

    def test_attribute_failure_returns_structured_fallback_when_agent_fails(self):
        spec = ProjectSpec(project_id="demo", name="Demo")
        trace = RunTrace(
            trace_id="t1",
            project_id="demo",
            input={"case_id": "c1", "query": "find clients"},
            normalized_request={"query": "find clients"},
            extracted_output={"filters": []},
        )
        judge = JudgeResult(
            trace_id="t1",
            project_id="demo",
            verdict="incorrect",
            fulfillment_assessments=[{"expectation_id": "e1", "status": "not_fulfilled"}],
            overall_fulfillment={"status": "not_fulfilled"},
            expected={"filters": ["age"]},
            evidence=["missing age filter"],
        )
        llm = Mock()
        llm.complete_json.return_value = {"error": "llm_request_failed", "raw_text": "boom"}

        result = attribute_failure(spec, trace, judge, llm=llm)

        self.assertEqual(result.analysis_method, "llm_call_failed")
        self.assertEqual(result.causal_category, "insufficient_evidence")
        self.assertIn("attribute_blocked", result.quality_flags)
        self.assertEqual(result.raw_model_output["error"], "llm_request_failed")


if __name__ == "__main__":
    unittest.main()
