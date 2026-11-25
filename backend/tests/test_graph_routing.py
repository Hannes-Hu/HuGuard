"""
Tests for the cyclic LangGraph routing logic and Human-in-the-Loop interrupt.

These are the most important tests in the suite because they verify the
non-linear graph behaviour that distinguishes this from a simple chain.

We mock the individual agent node functions (not ChatOllama) so we test
the graph routing decisions in isolation from LLM behaviour.
"""

from __future__ import annotations

from app.agents.critic import _build_state_after_critic
from app.schemas.audit import (
    AgentNode,
    ApprovalDecision,
    ASTReport,
    AuditState,
    AuditStatus,
    CriticOutput,
    CriticVerdict,
    PatcherOutput,
    ScannerOutput,
    SecurityFinding,
    Severity,
    UnifiedDiff,
)


def _make_full_state_with_patch(verdict: CriticVerdict, retry_count: int = 0) -> AuditState:
    """Build a realistic state at the point just after the Critic runs."""
    finding = SecurityFinding(
        id="abc12345",
        title="SQL Injection",
        description="Direct string concat in SQL query",
        severity=Severity.CRITICAL,
        category="sql-injection",
        affected_lines=[12],
        cwe_id="CWE-89",
    )
    scanner_out = ScannerOutput(
        findings=[finding], summary="Critical SQL injection", risk_score=90
    )
    diff = UnifiedDiff(
        original_snippet='query = "SELECT * FROM users WHERE id = " + user_id',
        patched_snippet='query = "SELECT * FROM users WHERE id = %s"\ncursor.execute(query, (user_id,))',
        unified_diff="--- a/vuln.py\n+++ b/vuln.py\n@@ -12 +12,2 @@\n-query...\n+query...",
        affected_lines=[12],
    )
    patcher_out = PatcherOutput(
        finding_id="abc12345",
        rationale="Parameterised query eliminates injection vector",
        diff=diff,
        is_breaking_change=False,
    )
    critic_out = CriticOutput(
        verdict=verdict,
        feedback="Looks good" if verdict == CriticVerdict.APPROVED else "Variable out of scope",
        syntax_valid=True,
        potential_side_effects=[],
    )
    return AuditState(
        thread_id="test-graph-thread",
        source_code='query = "SELECT * FROM users WHERE id = " + user_id',
        filename="vuln.py",
        language="python",
        ast_report=ASTReport(
            filename="vuln.py", language="python", symbols=[], total_lines=15, static_findings=[]
        ),
        scanner_output=scanner_out,
        patcher_output=patcher_out,
        critic_output=critic_out,
        patch_retry_count=retry_count,
    )


class TestCyclicRouting:
    def test_critic_approved_routes_to_human_review(self) -> None:
        """
        When the Critic approves, the state must transition to AWAITING_APPROVAL
        and current_node must be HUMAN_REVIEW. This is what triggers the
        LangGraph interrupt_before mechanism.
        """
        import structlog
        state = _make_full_state_with_patch(CriticVerdict.APPROVED)
        logger = structlog.get_logger()

        result = _build_state_after_critic(state, state.critic_output, logger)

        assert result.current_node == AgentNode.HUMAN_REVIEW
        assert result.status == AuditStatus.AWAITING_APPROVAL

    def test_critic_rejected_within_retry_budget_routes_back_to_patcher(self) -> None:
        """
        The defining cyclic behaviour: a rejected patch must loop back.
        This test proves the retry counter is incremented correctly.
        """
        import structlog
        state = _make_full_state_with_patch(CriticVerdict.REJECTED, retry_count=0)
        logger = structlog.get_logger()

        result = _build_state_after_critic(state, state.critic_output, logger)

        assert result.current_node == AgentNode.PATCHER
        assert result.status == AuditStatus.RUNNING
        assert result.patch_retry_count == 1

    def test_critic_rejected_at_max_retries_routes_to_done_with_failure(self) -> None:
        """
        When the retry budget is exhausted, the graph must terminate gracefully
        instead of looping forever. max_patch_retries defaults to 2 in settings.
        """
        from app.core.config import get_settings
        import structlog

        max_retries = get_settings().max_patch_retries
        # Set retry_count to max so the next rejection exhausts the budget
        state = _make_full_state_with_patch(CriticVerdict.REJECTED, retry_count=max_retries)
        logger = structlog.get_logger()

        result = _build_state_after_critic(state, state.critic_output, logger)

        assert result.current_node == AgentNode.DONE
        assert result.status == AuditStatus.FAILED
        assert result.error is not None
        assert "retries" in result.error.lower()

    def test_retry_count_carries_critic_feedback_into_next_patcher_call(self) -> None:
        """
        The Patcher must be able to read the previous Critic's rejection reason
        so it can self-correct. This tests that the state pipeline carries the
        feedback correctly without data loss.
        """
        import structlog
        state = _make_full_state_with_patch(CriticVerdict.REJECTED, retry_count=0)
        logger = structlog.get_logger()

        result = _build_state_after_critic(state, state.critic_output, logger)

        # The critic_output must be preserved in state for the Patcher to read
        assert result.critic_output is not None
        assert result.critic_output.feedback == "Variable out of scope"


class TestHumanInTheLoop:
    def test_approved_decision_transitions_status_to_approved(self) -> None:
        """
        Simulates what the human_review_node does after the user clicks Approve.
        The node reads the approval_decision from state and sets the final status.
        """
        from app.graph.audit_graph import _human_review_node

        state = _make_full_state_with_patch(CriticVerdict.APPROVED)
        state = state.model_copy(update={
            "approval_decision": ApprovalDecision.APPROVE,
            "status": AuditStatus.AWAITING_APPROVAL,
            "current_node": AgentNode.HUMAN_REVIEW,
        })

        result_dict = _human_review_node(state.model_dump(mode="json"))
        result = AuditState.model_validate(result_dict)

        assert result.status == AuditStatus.APPROVED
        assert result.current_node == AgentNode.DONE

    def test_rejected_decision_transitions_status_to_rejected(self) -> None:
        from app.graph.audit_graph import _human_review_node

        state = _make_full_state_with_patch(CriticVerdict.APPROVED)
        state = state.model_copy(update={
            "approval_decision": ApprovalDecision.REJECT,
            "status": AuditStatus.AWAITING_APPROVAL,
            "current_node": AgentNode.HUMAN_REVIEW,
        })

        result_dict = _human_review_node(state.model_dump(mode="json"))
        result = AuditState.model_validate(result_dict)

        assert result.status == AuditStatus.REJECTED
        assert result.current_node == AgentNode.DONE
