from unity_ludometry_mcp import errors
from unity_ludometry_mcp.protocol.generated import ErrorCodes


def test_every_agent_error_code_is_mapped() -> None:
    agent_codes = {v for k, v in vars(ErrorCodes).items() if k.isupper()}
    assert agent_codes == errors.AGENT_CODES_MAPPED


def test_mapping_follows_the_contract() -> None:
    cases = {
        "BAD_TOKEN": errors.PROVIDER_UNAVAILABLE, "HANDSHAKE_REQUIRED": errors.PROVIDER_UNAVAILABLE, "PROTOCOL_MISMATCH": errors.PROVIDER_UNAVAILABLE,
        "MODE_FORBIDDEN": errors.MODE_FORBIDDEN, "UNSUPPORTED": errors.CAPABILITY_UNAVAILABLE, "INDEX_STALE": errors.INDEX_STALE,
        "NOT_FOUND": errors.NOT_FOUND, "AMBIGUOUS": errors.AMBIGUOUS, "HANDLE_EXPIRED": errors.HANDLE_EXPIRED, "REF_EXPIRED": errors.REF_EXPIRED,
        "GAME_EXCEPTION": errors.GAME_EXCEPTION, "PATCH_FAILED": errors.PROVIDER_FAILED, "EXEC_FAILED": errors.PROVIDER_FAILED,
        "DUPLICATE_ASSEMBLY": errors.INTERNAL, "BUSY": errors.PROVIDER_FAILED, "TIMEOUT": errors.TIMEOUT, "CANCELLED": errors.CANCELLED,
        "MAIN_THREAD_UNAVAILABLE": errors.TIMEOUT, "IO_FAILED": errors.PROVIDER_FAILED, "INTERNAL": errors.PROVIDER_FAILED,
        "INVALID_FRAME": errors.INTERNAL, "FRAME_TOO_LARGE": errors.INTERNAL, "METHOD_NOT_FOUND": errors.INTERNAL, "INVALID_PARAMS": errors.INTERNAL,
    }
    for agent_code, ulm_code in cases.items():
        mapped = errors.map_agent_error({"code": agent_code, "message": "m"}, "obj.get")
        assert mapped.code == ulm_code, agent_code
        assert mapped.details["agentCode"] == agent_code
        assert mapped.details["method"] == "obj.get"
    assert errors.map_agent_error({"code": "BUSY", "message": "m"}).retryable
    assert not errors.map_agent_error({"code": "GAME_EXCEPTION", "message": "m"}).retryable


def test_mode_forbidden_needs_consent_and_keeps_agent_data() -> None:
    mapped = errors.map_agent_error({"code": "MODE_FORBIDDEN", "message": "m", "data": {"requiredMode": "Full", "hint": "Ask."}})
    assert mapped.needs == ["consent:runtime_set_mode"]
    assert mapped.details["requiredMode"] == "Full"
    assert mapped.hint.endswith("Ask.")


def test_unknown_agent_codes_are_generic_provider_failures() -> None:
    mapped = errors.map_agent_error({"code": "SOMETHING_NEW", "message": "m"})
    assert mapped.code == errors.PROVIDER_FAILED
    assert mapped.to_json()["details"]["agentCode"] == "SOMETHING_NEW"


def test_only_known_ulm_codes_can_be_raised() -> None:
    import pytest

    with pytest.raises(ValueError):
        errors.UlmError("NOT_A_CODE", "m")
