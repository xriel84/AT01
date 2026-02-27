"""Tests for GPU config, task routing, and Ollama delegation."""
import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestGpuConfig:

    def setup_method(self):
        from configs.gpu_config import reset_cache
        reset_cache()

    def test_get_gpu_tier_returns_int(self):
        from configs.gpu_config import get_gpu_tier
        tier = get_gpu_tier()
        assert isinstance(tier, int)
        assert tier in (0, 1, 2)

    def test_get_vram_gb_returns_int(self):
        from configs.gpu_config import get_vram_gb
        assert isinstance(get_vram_gb(), int)
        assert get_vram_gb() >= 0

    def test_get_whisper_config_tuple(self):
        from configs.gpu_config import get_whisper_config
        model, compute = get_whisper_config()
        assert model in ("small", "medium", "large-v3")
        assert compute in ("int8", "float16")

    def test_get_ollama_config_has_keys(self):
        from configs.gpu_config import get_ollama_config
        cfg = get_ollama_config()
        assert "host" in cfg
        assert "port" in cfg

    def test_can_run_known(self):
        from configs.gpu_config import can_run
        assert isinstance(can_run("mediapipe"), bool)

    def test_can_run_unknown_false(self):
        from configs.gpu_config import can_run
        assert can_run("nonexistent_xyz") is False

    def test_reset_cache(self):
        from configs import gpu_config
        gpu_config.get_gpu_config()
        gpu_config.reset_cache()
        assert gpu_config._CONFIG_CACHE is None

    def test_config_files_valid_json(self):
        config_dir = Path(__file__).parent.parent / "configs"
        for f in config_dir.glob("gpu_capabilities*.json"):
            with open(f) as fh:
                data = json.load(fh)
            assert "schema_version" in data
            assert "gpu" in data
            assert "tier" in data["gpu"]

    def test_tier_2_config_has_large_v3(self):
        config_dir = Path(__file__).parent.parent / "configs"
        main = config_dir / "gpu_capabilities.json"
        with open(main) as f:
            data = json.load(f)
        assert data["ml_capabilities"]["whisper_model"] == "large-v3"

    def test_stran_template_has_placeholders(self):
        config_dir = Path(__file__).parent.parent / "configs"
        stran = config_dir / "gpu_capabilities_stran.json"
        if stran.exists():
            with open(stran) as f:
                content = f.read()
            assert "__YD_" in content

    def test_detect_machine_env_var(self):
        from configs.gpu_config import _detect_machine_id
        with patch.dict("os.environ", {"AT01_MACHINE_ID": "testbox"}):
            assert _detect_machine_id() == "testbox"

    def test_fallback_config_for_unknown_machine(self):
        from configs.gpu_config import get_gpu_config
        config = get_gpu_config(machine_id="nonexistent_box_xyz")
        assert config["gpu"]["tier"] in (0, 1, 2)


class TestTaskRouter:

    def setup_method(self):
        from configs.gpu_config import reset_cache
        reset_cache()

    def test_known_task(self):
        from configs.task_router import get_task_config
        config = get_task_config("transcribe")
        assert "tier_used" in config
        assert "task" in config

    def test_unknown_task(self):
        from configs.task_router import get_task_config
        assert "error" in get_task_config("nonexistent_xyz")

    def test_all_configs_dict(self):
        from configs.task_router import get_all_task_configs
        configs = get_all_task_configs()
        assert isinstance(configs, dict)
        assert "transcribe" in configs

    def test_routing_json_valid(self):
        routing = Path(__file__).parent.parent / "configs" / "task_routing.json"
        with open(routing) as f:
            data = json.load(f)
        assert "routes" in data
        for name, route in data["routes"].items():
            assert "tiers" in route

    def test_tier2_transcribe_gets_large_v3(self):
        from configs.task_router import get_task_config
        config = get_task_config("transcribe")
        if config.get("tier_used") == 2:
            assert config["model"] == "large-v3"

    def test_all_routes_have_tier_0(self):
        routing = Path(__file__).parent.parent / "configs" / "task_routing.json"
        with open(routing) as f:
            data = json.load(f)
        for name, route in data["routes"].items():
            assert "0" in route["tiers"], f"Route {name} missing tier 0 fallback"


class TestOllamaDelegate:

    def test_structured_result(self):
        from agents.shared import ollama_delegate as od
        from configs.gpu_config import reset_cache
        reset_cache()

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"response": "test"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch.object(od, "_log_delegation"):
                result = od.delegate_to_ollama("test", model="mistral-nemo")

        assert result["status"] == "pass"
        assert "response" in result
        assert "duration_s" in result

    def test_error_returns_error_status(self):
        from agents.shared import ollama_delegate as od
        from configs.gpu_config import reset_cache
        reset_cache()

        with patch("urllib.request.urlopen", side_effect=Exception("conn refused")):
            with patch.object(od, "_log_delegation"):
                result = od.delegate_to_ollama("test", model="mistral-nemo")

        assert result["status"] == "error"

    def test_unfilled_template_returns_none(self):
        from agents.shared.ollama_delegate import _select_model
        cfg = {"max_model_for_planning": "__YD_FILL__", "default_worker_model": "mistral-nemo"}
        assert _select_model("planning", cfg) is None

    def test_worker_selects_default(self):
        from agents.shared.ollama_delegate import _select_model
        cfg = {"default_worker_model": "mistral-nemo"}
        assert _select_model("general", cfg) == "mistral-nemo"

    def test_no_model_returns_error(self):
        from agents.shared import ollama_delegate as od
        from configs.gpu_config import reset_cache
        reset_cache()

        with patch.object(od, "_select_model", return_value=None):
            with patch.object(od, "_log_delegation"):
                result = od.delegate_to_ollama("test", task_type="planning")

        assert result["status"] == "error"

    def test_result_has_timestamp(self):
        from agents.shared import ollama_delegate as od
        from configs.gpu_config import reset_cache
        reset_cache()

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"response": "ok"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch.object(od, "_log_delegation"):
                result = od.delegate_to_ollama("test", model="mistral-nemo")

        assert "timestamp" in result
        assert "T" in result["timestamp"]

    def test_context_appended(self):
        from agents.shared import ollama_delegate as od
        from configs.gpu_config import reset_cache
        reset_cache()

        captured = {}
        original_request = __import__("urllib.request", fromlist=["Request"]).Request

        def mock_request(url, data=None, headers=None):
            captured["data"] = json.loads(data.decode()) if data else None
            req = MagicMock()
            return req

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"response": "ok"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.Request", side_effect=mock_request):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                with patch.object(od, "_log_delegation"):
                    od.delegate_to_ollama("hello", context="world", model="mistral-nemo")

        assert "world" in captured["data"]["prompt"]


class TestPytestGpuMarkers:

    @pytest.mark.gpu_tier_1
    def test_tier1_marker(self):
        """Will skip on tier 0 machines."""
        pass

    @pytest.mark.gpu_tier_2
    def test_tier2_marker(self):
        """Will skip on tier 1 machines."""
        pass

    @pytest.mark.vram_min(8)
    def test_vram_min_8(self):
        """Will skip on machines with <8GB VRAM."""
        pass
