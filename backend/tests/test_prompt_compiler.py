"""The model-specific prompt compiler.

What matters here is not that a string comes out, but that the string is
actually different per family, that nothing is lost without being reported, and
that an unrecognised model is labelled as unrecognised rather than dressed up as
tailored.
"""

from __future__ import annotations

import pytest

from film.prompt_brief import brief_from_analysis, brief_from_shot
from film.prompt_compiler import ShotBrief, compile_for, compile_prompt, resolve_target


def a_brief(**overrides: object) -> ShotBrief:
    base = dict(
        scene_intent="Establish the diner before the argument",
        subjects=["Mara (late 30s, tired), looking wary"],
        action="She sets down a coffee pot and turns toward the door",
        location="A roadside diner at 4am, fogged windows",
        shot_size="medium shot",
        camera="three-quarter left angle, eye-level camera",
        lens="35mm, shallow depth of field",
        movement="slow push in",
        lighting="practical ceiling light, cold blue exterior",
        style="muted palette, film grain",
        audio="ambience: rain on glass",
        timeline="6 seconds at 24fps",
        continuity=["Mara wearing the green apron"],
        negative=["text", "watermark"],
    )
    base.update(overrides)
    return ShotBrief(**base)  # type: ignore[arg-type]


class TestTargetResolution:
    def test_known_families_are_recognised(self):
        for model, expected in [
            ("ltxv-13b-098-dev", "ltx"),
            ("lightricks/ltx-video", "ltx"),
            ("wavespeed-ai/wan-2.2/t2v-480p", "wan22"),
            ("wavespeed-ai/wan-2.1/t2v-480p", "wan"),
            ("hunyuan-video", "hunyuan"),
            ("fal-ai/flux/dev", "flux"),
            ("z_image", "z_image"),
            ("fal-ai/kling-video", "veo"),
        ]:
            target, matched = resolve_target(model)
            assert (target.id, matched) == (expected, True), model

    def test_an_unknown_model_is_reported_as_unknown(self):
        target, matched = resolve_target("some-model-released-next-year")
        assert matched is False
        assert target.id == "generic"
        # The caller must be able to say so, not just silently use a default.
        assert "does not have a convention" in target.note or "Not a model" in target.note

    def test_an_empty_model_id_does_not_match_anything(self):
        target, matched = resolve_target("")
        assert (target.id, matched) == ("generic", False)

    def test_a_convention_says_where_it_came_from(self):
        ltx, _ = resolve_target("ltxv-13b")
        sdxl, _ = resolve_target("sdxl-turbo")
        generic, _ = resolve_target("unknown")
        # These are different claims and must not be stored identically.
        assert ltx.basis == "publisher_guidance"
        assert sdxl.basis == "community_convention"
        assert generic.basis == "tfg_default"


class TestCompilation:
    def test_the_same_brief_reads_differently_per_family(self):
        brief = a_brief()
        ltx = compile_prompt(brief, "ltxv-13b-098-dev").prompt
        wan = compile_prompt(brief, "wavespeed-ai/wan-2.2/t2v-480p").prompt
        sdxl = compile_prompt(brief, "sdxl-turbo").prompt
        assert ltx != wan != sdxl
        assert ltx != sdxl
        # The shapes are the point, not the wording.
        assert "Subject:" in wan and "Motion:" in wan
        assert "Subject:" not in ltx
        assert sdxl.count(",") > sdxl.count(".")

    def test_the_action_survives_into_every_target(self):
        brief = a_brief()
        for model in ("ltxv-13b", "wan2.2", "sdxl-turbo", "fal-ai/flux/dev", "unknown-model"):
            assert "coffee pot" in compile_prompt(brief, model).prompt, model

    def test_scene_intent_is_never_sent_to_a_render_model(self):
        """It says what the shot is for; no model can render a purpose."""
        brief = a_brief()
        for model in ("ltxv-13b", "wan2.2", "sdxl-turbo"):
            compiled = compile_prompt(brief, model)
            assert "Establish the diner" not in compiled.prompt
            # And it must not be reported as dropped, having never been sent.
            assert not any("intent" in reason for reason in compiled.dropped)

    def test_an_empty_brief_produces_an_empty_prompt_not_filler(self):
        compiled = compile_prompt(ShotBrief(), "ltxv-13b")
        assert compiled.prompt == ""
        assert compiled.negative_prompt == ""


class TestNothingIsLostSilently:
    def test_a_still_model_drops_motion_and_says_so(self):
        compiled = compile_prompt(a_brief(), "fal-ai/flux/dev")
        assert "push in" not in compiled.prompt
        assert any("movement" in reason and "still" in reason for reason in compiled.dropped)
        assert any("timeline" in reason for reason in compiled.dropped)

    def test_a_model_with_no_negative_prompt_reports_the_constraints_it_cannot_take(self):
        compiled = compile_prompt(a_brief(), "fal-ai/flux/dev")
        assert compiled.negative_prompt == ""
        assert any("negative" in reason for reason in compiled.dropped)

    def test_audio_is_dropped_for_silent_models_and_kept_for_sounding_ones(self):
        silent = compile_prompt(a_brief(), "ltxv-13b")
        sounding = compile_prompt(a_brief(), "fal-ai/veo-3")
        assert "rain on glass" not in silent.prompt
        assert any("audio" in reason for reason in silent.dropped)
        assert "rain on glass" in sounding.prompt

    def test_going_over_budget_gives_up_decoration_before_substance(self):
        brief = a_brief(style="x" * 900, lighting="y" * 900, action="She turns toward the door")
        compiled = compile_prompt(brief, "sdxl-turbo")
        assert len(compiled.prompt) <= 600
        assert "She turns toward the door" in compiled.prompt
        assert compiled.dropped, "a trimmed prompt must say what it lost"

    def test_a_brief_within_budget_loses_nothing_to_length(self):
        compiled = compile_prompt(a_brief(), "ltxv-13b")
        assert not any("budget" in reason for reason in compiled.dropped)

    def test_continuity_is_never_traded_for_length(self):
        brief = a_brief(style="x" * 2000, continuity=["Mara wearing the green apron"])
        compiled = compile_prompt(brief, "wan2.2")
        assert "green apron" in compiled.prompt


class TestCompileFor:
    def test_blanks_and_duplicates_are_skipped(self):
        results = compile_for(a_brief(), ["ltxv-13b", "", "ltxv-13b", "  ", "wan2.2"])
        assert sorted(results) == ["ltxv-13b", "wan2.2"]


class TestBriefsFromTheApp:
    def test_a_storyboard_shot_becomes_a_brief(self, client):
        project_id = "compiler-project"
        scene = client.post(f"/api/film/projects/{project_id}/scenes", json={"title": "Diner"}).json()["id"]
        shot_id = client.post(
            f"/api/film/projects/{project_id}/scenes/{scene}/shots",
            json={"title": "Mara pours", "action": "She sets down a coffee pot"},
        ).json()["id"]

        from state import get_state_service

        handler = get_state_service()
        project = handler.film.get_project(project_id)
        found = project.find_shot(shot_id)
        assert found is not None
        brief = brief_from_shot(project, found[0], found[1])
        assert "coffee pot" in brief.action
        assert brief.shot_size, "framing must reach the brief"

    def test_an_analysed_shot_becomes_a_brief(self, client, video):
        analysis = client.post(
            "/api/video-analysis/import", json={"path": str(video), "title": "Clip"}
        ).json()
        detected = client.post(f"/api/video-analysis/{analysis['id']}/detect").json()
        client.post(f"/api/video-analysis/{analysis['id']}/analyze", json={})
        analysed = client.get(f"/api/video-analysis/{analysis['id']}").json()

        from state import get_state_service

        stored = get_state_service().video_analysis.store.load(analysis["id"])
        brief = brief_from_analysis(stored, stored.shots[0])
        assert brief.timeline, "a measured duration must reach the brief"
        assert detected["shots"], "the fixture must actually produce shots"
        assert analysed["stage"] == "complete"


class TestRoutes:
    def test_the_targets_are_inspectable(self, client):
        body = client.get("/api/prompts/targets").json()
        ids = {target["id"] for target in body["targets"]}
        assert {"ltx", "wan", "sdxl", "generic"} <= ids
        # The rule that classifies a model must be visible, not just its result.
        ltx = next(t for t in body["targets"] if t["id"] == "ltx")
        assert "ltx" in ltx["matches"]

    def test_compiling_from_an_explicit_brief(self, client):
        response = client.post(
            "/api/prompts/compile",
            json={
                "models": ["ltxv-13b", "wan2.2", "unknown-model"],
                "brief": a_brief().model_dump(),
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert [p["model"] for p in body["prompts"]] == ["ltxv-13b", "wan2.2", "unknown-model"]
        assert body["prompts"][0]["matched"] is True
        assert body["prompts"][2]["matched"] is False
        assert body["brief"]["action"].startswith("She sets down")

    def test_compiling_from_a_storyboard_shot(self, client):
        project_id = "compiler-routes"
        scene = client.post(f"/api/film/projects/{project_id}/scenes", json={"title": "S"}).json()["id"]
        shot_id = client.post(
            f"/api/film/projects/{project_id}/scenes/{scene}/shots",
            json={"title": "Shot", "action": "She turns toward the door"},
        ).json()["id"]
        body = client.post(
            "/api/prompts/compile",
            json={"models": ["ltxv-13b"], "project_id": project_id, "scene_id": scene, "shot_id": shot_id},
        ).json()
        assert "turns toward the door" in body["prompts"][0]["prompt"]

    @pytest.mark.parametrize(
        "payload",
        [
            {"models": ["ltxv-13b"]},
            {"models": ["ltxv-13b"], "brief": {}, "project_id": "p", "shot_id": "s"},
        ],
    )
    def test_an_ambiguous_or_missing_source_is_refused(self, client, payload: dict[str, object]):
        assert client.post("/api/prompts/compile", json=payload).status_code == 400

    def test_a_missing_shot_is_a_404(self, client):
        client.post("/api/film/projects/compiler-404/scenes", json={"title": "S"})
        response = client.post(
            "/api/prompts/compile",
            json={"models": ["ltxv-13b"], "project_id": "compiler-404", "shot_id": "no-such-shot"},
        )
        assert response.status_code == 404


class TestReversePromptsAreFilled:
    def test_model_specific_is_no_longer_empty_after_analysis(self, client, video):
        analysis = client.post(
            "/api/video-analysis/import", json={"path": str(video), "title": "Clip"}
        ).json()
        client.post(f"/api/video-analysis/{analysis['id']}/detect")
        analysed = client.post(f"/api/video-analysis/{analysis['id']}/analyze", json={}).json()
        prompts = analysed["shots"][0]["prompts"]
        assert prompts["model_specific"], "the compiler must fill this"
        # The local host is always a possibility, so it is always compiled for.
        assert any("ltx" in model for model in prompts["model_specific"])

    def test_the_configured_model_is_compiled_for(self, client, video):
        client.post("/api/settings", json={"default_video_model": "wavespeed-ai/wan-2.2/t2v-480p"})
        analysis = client.post(
            "/api/video-analysis/import", json={"path": str(video), "title": "Clip"}
        ).json()
        client.post(f"/api/video-analysis/{analysis['id']}/detect")
        analysed = client.post(f"/api/video-analysis/{analysis['id']}/analyze", json={}).json()
        model_specific = analysed["shots"][0]["prompts"]["model_specific"]
        assert "wavespeed-ai/wan-2.2/t2v-480p" in model_specific
        # And compiled in Wan's shape — labelled clauses — rather than copied
        # from the LTX one, which is the same brief as flowing prose.
        wan = model_specific["wavespeed-ai/wan-2.2/t2v-480p"]
        assert ":" in wan and "Timing:" in wan
        assert wan != model_specific["ltx-2"]
