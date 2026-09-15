"""The knowledge engine: recording, derivation, controls, routing.

The point of these tests is the honesty of the conclusions, not just that rows
land in a table: a count must be stated as a fact, a generalisation from three
runs must be labelled a hypothesis, and turning learning off must stop
collection rather than hide it.
"""

from __future__ import annotations

import pytest

from film.knowledge_models import KnowledgeEvent
from handlers.knowledge_handler import confidence_for

MODEL = "ltx2-fast"


def _generate(knowledge, *, outcome: str, model: str = MODEL, error: str = "", seconds: float = 12.0):
    return knowledge.record_generation(
        outcome=outcome, model=model, provider="wangp", project_id="p1", shot_id="s1",
        execution_mode="wangp", duration_seconds=seconds, error=error,
    )


def _judge(knowledge, kind: str, model: str = MODEL):
    return knowledge.record(KnowledgeEvent(kind=kind, model=model, provider="wangp"))  # type: ignore[arg-type]


def _statements(profile) -> dict[str, str]:
    """statement -> kind, for asserting how a conclusion is labelled."""
    return {observation.statement: observation.kind for observation in profile.observations}


class TestConfidence:
    def test_confidence_grows_with_evidence_but_never_reaches_certainty(self):
        assert confidence_for(0) == 0.0
        assert confidence_for(1) < confidence_for(5) < confidence_for(20)
        assert confidence_for(1000) < 1.0


class TestRecording:
    def test_a_render_outcome_is_recorded_and_counted(self, test_state):
        knowledge = test_state.knowledge
        _generate(knowledge, outcome="success")
        _generate(knowledge, outcome="failure", error="CUDA out of memory")
        profile = knowledge.profile(MODEL)
        assert profile.successes == 1
        assert profile.failures == 1
        assert profile.success_rate == 0.5

    def test_the_generation_queue_feeds_the_engine(self, client, test_state):
        """Not a unit of the handler: the real queue must actually report."""
        project = "knowledge-project"
        scene = client.post(f"/api/film/projects/{project}/scenes", json={"title": "S"}).json()["id"]
        shot = client.post(
            f"/api/film/projects/{project}/scenes/{scene}/shots", json={"title": "Shot"}
        ).json()["id"]
        client.post(
            f"/api/film/projects/{project}/scenes/{scene}/shots/{shot}/generate", json={"kind": "preview"}
        )
        events = test_state.knowledge.recent_events(project_id=project, limit=10)
        assert events, "the queue recorded nothing"
        assert events[0].shot_id == shot
        assert events[0].category == "generation"


class TestDerivation:
    def test_counts_are_stated_as_facts_with_full_confidence(self, test_state):
        knowledge = test_state.knowledge
        for _ in range(3):
            _generate(knowledge, outcome="success")
        profile = knowledge.profile(MODEL)
        facts = [o for o in profile.observations if o.kind == "fact"]
        assert facts, "no fact was derived from three completed runs"
        assert all(observation.confidence == 1.0 for observation in facts)
        assert any("Completed 3 of 3" in observation.statement for observation in facts)

    def test_a_small_sample_is_labelled_a_hypothesis_not_a_pattern(self, test_state):
        knowledge = test_state.knowledge
        _generate(knowledge, outcome="failure", error="boom")
        _generate(knowledge, outcome="failure", error="boom")
        profile = knowledge.profile(MODEL)
        failing = _statements(profile).get("Fails more often than it succeeds on this machine.")
        assert failing == "hypothesis", "two runs must not be presented as an established pattern"

    def test_enough_evidence_promotes_it_to_an_observed_pattern(self, test_state):
        knowledge = test_state.knowledge
        for _ in range(6):
            _generate(knowledge, outcome="failure", error="CUDA out of memory")
        profile = knowledge.profile(MODEL)
        assert _statements(profile).get("Fails more often than it succeeds on this machine.") == "observed_pattern"

    def test_approvals_become_a_user_preference_once_there_are_enough(self, test_state):
        knowledge = test_state.knowledge
        for _ in range(4):
            _judge(knowledge, "version_approved")
        profile = knowledge.profile(MODEL)
        assert _statements(profile).get("You usually keep what this model produces.") == "user_preference"

    def test_a_recurring_error_is_surfaced_with_its_message(self, test_state):
        knowledge = test_state.knowledge
        for _ in range(3):
            _generate(knowledge, outcome="failure", error="CUDA out of memory at 1080p")
        profile = knowledge.profile(MODEL)
        recurring = [o for o in profile.observations if o.statement.startswith("Recurring failure")]
        assert recurring and "CUDA out of memory at 1080p" in recurring[0].statement

    def test_a_reliable_model_earns_a_recommendation(self, test_state):
        knowledge = test_state.knowledge
        for _ in range(6):
            _generate(knowledge, outcome="success")
        profile = knowledge.profile(MODEL)
        assert any(o.kind == "model_recommendation" for o in profile.observations)

    def test_an_unreliable_model_earns_none(self, test_state):
        knowledge = test_state.knowledge
        for _ in range(6):
            _generate(knowledge, outcome="failure", error="boom")
        profile = knowledge.profile(MODEL)
        assert not any(o.kind == "model_recommendation" for o in profile.observations)


class TestLearningControls:
    def test_disabling_learning_stops_collection_not_just_display(self, client, test_state):
        client.put("/api/knowledge/settings", json={"enabled": False})
        assert _generate(test_state.knowledge, outcome="success") is None
        assert test_state.knowledge.store.event_count() == 0

    def test_a_single_category_can_be_switched_off(self, client, test_state):
        client.put(
            "/api/knowledge/settings",
            json={"enabled": True, "generation": False, "approval": True, "editing": True, "feedback": True},
        )
        assert _generate(test_state.knowledge, outcome="success") is None
        assert _judge(test_state.knowledge, "version_approved") is not None

    def test_feedback_reports_declined_rather_than_failing(self, client):
        client.put("/api/knowledge/settings", json={"enabled": False})
        response = client.post("/api/knowledge/feedback", json={"model": MODEL, "rating": 5})
        assert response.status_code == 200
        assert response.json()["status"] == "declined"

    def test_resetting_one_model_leaves_the_others(self, client, test_state):
        knowledge = test_state.knowledge
        _generate(knowledge, outcome="success", model="a")
        _generate(knowledge, outcome="success", model="b")
        client.post("/api/knowledge/reset", json={"model": "a"})
        assert knowledge.profile("a").runs == 0
        assert knowledge.profile("b").runs == 1

    def test_resetting_a_project_leaves_model_knowledge_from_elsewhere(self, client, test_state):
        knowledge = test_state.knowledge
        knowledge.record(KnowledgeEvent(kind="generation_completed", model=MODEL, project_id="keep"))
        knowledge.record(KnowledgeEvent(kind="generation_completed", model=MODEL, project_id="drop"))
        client.post("/api/knowledge/reset", json={"project_id": "drop"})
        assert knowledge.profile(MODEL).runs == 1


class TestExportImport:
    def test_knowledge_round_trips_between_machines(self, client, test_state):
        for _ in range(3):
            _generate(test_state.knowledge, outcome="success")
        exported = client.get("/api/knowledge/export").json()
        assert len(exported["events"]) == 3

        client.post("/api/knowledge/reset", json={})
        assert test_state.knowledge.store.event_count() == 0

        imported = client.post("/api/knowledge/import", json={"payload": exported, "replace": False})
        assert imported.status_code == 200
        assert test_state.knowledge.profile(MODEL).successes == 3

    def test_an_unknown_export_version_is_refused(self, client):
        response = client.post(
            "/api/knowledge/import",
            json={"payload": {"schema_version": 99, "events": [], "observations": []}},
        )
        assert response.status_code == 400


class TestRecommendation:
    def test_it_prefers_the_model_with_the_better_record(self, client, test_state):
        knowledge = test_state.knowledge
        for _ in range(8):
            _generate(knowledge, outcome="success", model="reliable")
        for _ in range(8):
            _generate(knowledge, outcome="failure", model="flaky", error="boom")
        result = client.post(
            "/api/knowledge/recommend", json={"task": "video", "candidates": ["flaky", "reliable"]}
        ).json()
        assert result["model"] == "reliable"
        assert "8 runs" in result["reason"]

    def test_with_no_history_it_says_so_instead_of_inventing_a_preference(self, client):
        result = client.post(
            "/api/knowledge/recommend", json={"task": "video", "candidates": ["unknown-a", "unknown-b"]}
        ).json()
        assert result["model"] in {"unknown-a", "unknown-b"}
        assert "not a recommendation" in result["reason"]

    def test_no_candidates_yields_no_model(self, client):
        result = client.post("/api/knowledge/recommend", json={"task": "video", "candidates": []}).json()
        assert result["model"] == ""


class TestSummaryAndProfiles:
    def test_the_summary_counts_what_is_stored(self, client, test_state):
        for _ in range(4):
            _generate(test_state.knowledge, outcome="success")
        summary = client.get("/api/knowledge").json()
        assert summary["event_count"] == 4
        assert summary["model_count"] == 1
        assert summary["observation_count"] >= 1
        assert summary["learning"]["enabled"] is True

    def test_profiles_are_listed_with_their_observations(self, client, test_state):
        for _ in range(5):
            _generate(test_state.knowledge, outcome="success")
        models = client.get("/api/knowledge/models").json()["models"]
        assert models[0]["model"] == MODEL
        assert models[0]["observations"]


class TestPromptPatterns:
    """Which prompt vocabulary worked is counted, never asserted."""

    def _with_prompt(self, knowledge, *, outcome: str, prompt: str):
        return knowledge.record_generation(
            outcome=outcome, model=MODEL, provider="wangp", project_id="p1",
            shot_id="s1", execution_mode="wangp", prompt=prompt, duration_seconds=8.0,
        )

    def test_a_phrase_used_once_gets_no_verdict(self, test_state):
        knowledge = test_state.knowledge
        self._with_prompt(knowledge, outcome="success", prompt="A handheld shot of a street")
        patterns = {p.phrase: p for p in knowledge.prompt_patterns(MODEL)}
        assert patterns["handheld"].uses == 1
        # One success is not a technique.
        assert patterns["handheld"].verdict == "unclear"

    def test_a_phrase_that_keeps_working_is_reported_as_working(self, test_state):
        knowledge = test_state.knowledge
        for _ in range(4):
            self._with_prompt(knowledge, outcome="success", prompt="golden hour over the water")
        patterns = {p.phrase: p for p in knowledge.prompt_patterns(MODEL)}
        assert patterns["golden hour"].verdict == "worked"
        assert patterns["golden hour"].successes == 4
        assert 0.0 < patterns["golden hour"].confidence < 1.0

    def test_a_phrase_that_keeps_failing_is_reported_as_struggling(self, test_state):
        knowledge = test_state.knowledge
        for _ in range(4):
            self._with_prompt(knowledge, outcome="failure", prompt="an extreme close-up of an eye")
        patterns = {p.phrase: p for p in knowledge.prompt_patterns(MODEL)}
        assert patterns["extreme close-up"].verdict == "struggled"
        assert patterns["extreme close-up"].failures == 4

    def test_phrases_the_user_never_wrote_are_absent(self, test_state):
        knowledge = test_state.knowledge
        self._with_prompt(knowledge, outcome="success", prompt="a plain description with no craft terms")
        assert knowledge.prompt_patterns(MODEL) == []

    def test_patterns_reach_the_profile_and_the_api(self, client, test_state):
        knowledge = test_state.knowledge
        for _ in range(3):
            self._with_prompt(knowledge, outcome="success", prompt="slow motion, film grain")
        profile = knowledge.profile(MODEL)
        assert {p.phrase for p in profile.prompt_patterns} == {"slow motion", "film grain"}

        body = client.get("/api/knowledge/models").json()
        served = next(m for m in body["models"] if m["model"] == MODEL)
        assert {p["phrase"] for p in served["prompt_patterns"]} == {"slow motion", "film grain"}


class TestApprovalsAreRecorded:
    """Approving a shot is a judgement about the model that made it."""

    def _rendered_shot(self, client) -> tuple[str, str, str]:
        project = "approval-project"
        scene = client.post(f"/api/film/projects/{project}/scenes", json={"title": "S"}).json()["id"]
        shot = client.post(
            f"/api/film/projects/{project}/scenes/{scene}/shots", json={"title": "Shot"}
        ).json()["id"]
        client.post(
            f"/api/film/projects/{project}/scenes/{scene}/shots/{shot}/generate", json={"kind": "preview"}
        )
        return project, scene, shot

    def test_approving_a_shot_is_recorded_against_its_model(self, client, test_state):
        project, scene, shot = self._rendered_shot(client)
        before = len(test_state.knowledge.recent_events(limit=500))
        response = client.put(
            f"/api/film/projects/{project}/scenes/{scene}/shots/{shot}", json={"status": "approved"}
        )
        assert response.status_code == 200
        kinds = [event.kind for event in test_state.knowledge.recent_events(limit=500)]
        assert "version_approved" in kinds
        assert len(kinds) > before

    def test_rejecting_a_shot_is_recorded_too(self, client, test_state):
        project, scene, shot = self._rendered_shot(client)
        client.put(
            f"/api/film/projects/{project}/scenes/{scene}/shots/{shot}", json={"status": "rejected"}
        )
        kinds = [event.kind for event in test_state.knowledge.recent_events(limit=500)]
        assert "version_rejected" in kinds

    def test_resaving_an_approved_shot_is_not_a_second_endorsement(self, client, test_state):
        project, scene, shot = self._rendered_shot(client)
        path = f"/api/film/projects/{project}/scenes/{scene}/shots/{shot}"
        client.put(path, json={"status": "approved"})
        client.put(path, json={"status": "approved"})
        kinds = [event.kind for event in test_state.knowledge.recent_events(limit=500)]
        assert kinds.count("version_approved") == 1

    def test_approval_is_not_recorded_when_that_category_is_off(self, client, test_state):
        project, scene, shot = self._rendered_shot(client)
        client.put("/api/knowledge/settings", json={
            "enabled": True, "generation": True, "approval": False, "editing": True, "feedback": True,
        })
        client.put(
            f"/api/film/projects/{project}/scenes/{scene}/shots/{shot}", json={"status": "approved"}
        )
        kinds = [event.kind for event in test_state.knowledge.recent_events(limit=500)]
        assert "version_approved" not in kinds

    def test_the_shot_is_still_approved_even_if_learning_is_off(self, client, test_state):
        """Learning is advisory: switching it off must not change the edit."""
        project, scene, shot = self._rendered_shot(client)
        client.put("/api/knowledge/settings", json={
            "enabled": False, "generation": True, "approval": True, "editing": True, "feedback": True,
        })
        body = client.put(
            f"/api/film/projects/{project}/scenes/{scene}/shots/{shot}", json={"status": "approved"}
        ).json()
        assert body["status"] == "approved"
