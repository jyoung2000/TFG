"""Thumbs up / thumbs down (user, 2026-10-03: "Let the user grade prompts,
styleguides, videos, and images the software creates with a simple thumbs up
and thumbs down ... so the software can generate to the users taste and
preference", and grade LoRAs so the software can "use that data to train and
generate LoRA's the user likes")."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from film.taste import TasteVote, prompt_phrases, summarize, taste_note
from tests.test_face_consistency import PROJECT, _big_png, _raven
from tests.test_film_openrouter import _or_text, _set_openrouter_key


def _vote(client, **body) -> dict:
    response = client.post("/api/taste/vote", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_a_vote_is_kept_changed_and_taken_back(client) -> None:
    _vote(client, kind="image", subject="C:/renders/a.png", vote=1, prompt="rvnx, woman, soft studio light", model="z_image")
    _vote(client, kind="image", subject="C:/renders/a.png", vote=-1, prompt="rvnx, woman, soft studio light", model="z_image")
    votes = client.get("/api/taste/votes").json()["votes"]
    assert len(votes) == 1 and votes[0]["vote"] == -1, "one vote per thing: the latest"
    assert votes[0]["file"].endswith("a.png")
    assert _vote(client, kind="image", subject="C:/renders/a.png", vote=0)["vote"] is None
    assert client.get("/api/taste/votes").json()["votes"] == []


def test_prompt_phrases_are_the_comma_separated_parts() -> None:
    assert prompt_phrases("RVNX, woman,  Soft studio light; red lips\nfilm grain, a") == ["rvnx", "woman", "soft studio light", "red lips", "film grain"]


def test_the_summary_learns_liked_and_disliked_phrases() -> None:
    votes = [
        TasteVote(kind="image", subject=f"up{i}", vote=1, prompt=f"woman, soft studio light, shot {i}") for i in range(3)
    ] + [
        TasteVote(kind="video", subject=f"down{i}", vote=-1, prompt=f"woman, neon lights, take {i}") for i in range(2)
    ]
    summary = summarize(votes)
    assert [p.text for p in summary.liked_phrases] == ["soft studio light"], "one vote is not a taste; 'woman' is even"
    assert [p.text for p in summary.disliked_phrases] == ["neon lights"]
    note = taste_note(summary)
    assert "soft studio light" in note and "neon lights" in note


def test_the_liked_loras_training_settings_are_learned() -> None:
    def lora(subject: str, vote: int, resolution: int, steps: int) -> TasteVote:
        return TasteVote(kind="lora", subject=subject, vote=vote, meta={"resolution": resolution, "steps": steps, "batch_size": 2})  # type: ignore[arg-type]

    summary = summarize([lora("a", 1, 384, 300), lora("b", 1, 384, 300), lora("c", -1, 512, 150), lora("d", 1, 512, 150)])
    assert summary.training is not None
    assert (summary.training.resolution, summary.training.steps, summary.training.liked) == (384, 300, 2)
    assert summary.liked_loras == ["a", "b", "d"] and summary.disliked_loras == ["c"]


def test_a_lora_vote_remembers_the_lora(client, tmp_path: Path) -> None:
    lora = tmp_path / "raven.safetensors"
    lora.write_bytes(b"0" * 64)
    entry = client.post("/api/training/loras/import", json={"path": str(lora), "name": "Raven", "target": "z_image", "trigger": "rvnx"}).json()
    stored = _vote(client, kind="lora", subject=entry["id"], vote=1)["vote"]
    assert stored["model"] == "z_image" and stored["prompt"] == "rvnx"


def test_a_vote_rates_the_model_in_learning(client) -> None:
    _vote(client, kind="video", subject="C:/renders/b.mp4", vote=1, prompt="a rooftop at dusk", model="ltx2_22B_distilled")
    events = client.get("/api/knowledge/events").json()
    rated = [e for e in events if e["kind"] == "rating"]
    assert rated and rated[0]["rating"] == 5 and rated[0]["model"] == "ltx2_22B_distilled"


def test_with_learning_from_feedback_off_votes_are_kept_but_not_learned(client) -> None:
    client.put("/api/knowledge/settings", json={"enabled": True, "generation": True, "approval": True, "editing": True, "feedback": False})
    for i in range(3):
        _vote(client, kind="image", subject=f"C:/renders/{i}.png", vote=1, prompt="soft studio light")
    summary = client.get("/api/taste/summary").json()
    assert summary["enabled"] is False and summary["votes"] == 3 and summary["liked_phrases"] == []


def test_the_lora_dataset_follows_the_users_grades(client, test_state, fake_services, create_fake_model_files, tmp_path: Path) -> None:
    """A style-guide image graded down stays out of the character's LoRA; a
    render graded up that was made with the character's LoRA goes in."""
    create_fake_model_files(include_zit=True)
    asset = _raven(client, test_state, fake_services)
    base = f"/api/film/projects/{PROJECT}/assets/{asset['id']}"
    for name in ("Raven-front-view", "Raven-profile-view"):
        client.post(f"{base}/references", json={"image_base64": _big_png(), "name_hint": name})
    assets = client.get(f"/api/film/projects/{PROJECT}").json()["project"]["assets"]
    references = next(a for a in assets if a["id"] == asset["id"])["reference_images"]
    profile = next(r for r in references if "Raven-profile-view" in r)
    _vote(client, kind="style_guide", subject=profile, project_id=PROJECT, vote=-1)

    lora = tmp_path / "raven.safetensors"
    lora.write_bytes(b"0" * 64)
    entry = client.post("/api/training/loras/import", json={"path": str(lora), "name": "Raven", "target": "z_image", "trigger": "rvnx"}).json()
    client.put(f"/api/film/projects/{PROJECT}/assets/{asset['id']}", json={"lora_id": entry["id"]})
    renders = tmp_path / "renders"
    renders.mkdir()
    liked = renders / "liked-render.png"
    Image.new("RGB", (64, 64), (1, 2, 3)).save(liked)
    _vote(client, kind="image", subject=str(liked), vote=1, prompt="rvnx, woman", loras=[entry["file"]])
    unrelated = renders / "other-render.png"
    Image.new("RGB", (64, 64), (4, 5, 6)).save(unrelated)
    _vote(client, kind="image", subject=str(unrelated), vote=1, prompt="a lighthouse")

    files = [i["file"] for i in client.post(f"{base}/dataset", json={}).json()["items"]]
    assert any("front-view" in f for f in files)
    assert not any("profile-view" in f for f in files), "graded down: left out"
    assert any("liked-render" in f for f in files), "graded up and made with this LoRA: in"
    assert not any("other-render" in f for f in files), "graded up, but not this character"


def test_the_director_is_told_the_users_taste(client, test_state) -> None:
    for i in range(2):
        _vote(client, kind="image", subject=f"C:/renders/u{i}.png", vote=1, prompt=f"moody rim light, take {i}")
        _vote(client, kind="video", subject=f"C:/renders/d{i}.mp4", vote=-1, prompt=f"handheld shaky cam, take {i}")
    _set_openrouter_key(client)
    test_state.http.queue("post", _or_text('{"summary": "nothing", "commands": []}'))
    client.post(f"/api/film/projects/{PROJECT}/director/instruct", json={"instruction": "plan the opening"})
    payload = test_state.http.calls[-1].json_payload
    assert payload is not None
    system = payload["messages"][0]["content"]
    assert "moody rim light" in system and "handheld shaky cam" in system
    assert "thumbs" in json.dumps(payload["messages"][0])
