"""Character LoRA datasets that learn the person (see film/identity_dataset.py).

MEASURED 2026-10-02: Raven's 1100-step run rendered the bird at every sample -
the captions carried her whole look and the trigger was the word "raven".
"""

from __future__ import annotations

from PIL import Image

from film.identity_dataset import character_caption, face_crop, face_crop_name, rare_trigger, source_crops


def test_the_default_trigger_is_not_an_english_word() -> None:
    assert rare_trigger("Raven") == "rvnx"
    assert rare_trigger("Sarah") == "srhx"
    assert rare_trigger("Ai") == "aix"
    assert rare_trigger("!!") == "subjx"


def test_a_character_caption_says_only_what_varies() -> None:
    florence = "A woman with dark wavy hair wearing a black leather jumpsuit stands against a grey wall."
    caption = character_caption(florence, "rvnx", "1790927617347-Raven-closeup-34-left.png")
    assert caption == "rvnx, woman, close-up portrait, three-quarter view from the left"
    for look in ("hair", "leather", "jumpsuit", "grey", "wall"):
        assert look not in caption
    assert character_caption(florence, "rvnx", "Raven-full-back-34-right.png") == "rvnx, woman, full body shot, three-quarter back view from the right"
    assert character_caption(florence, "rvnx", "Raven-profile-view.png") == "rvnx, woman, profile view"
    assert character_caption("", "rvnx", "1790920286007-6.jpg.png") == "rvnx, person"
    assert character_caption(florence, "rvnx", "Raven-source-face.png") == "rvnx, woman, close-up portrait"


def test_source_crops_frame_the_real_face() -> None:
    photo = Image.new("RGB", (1125, 2000))
    face = [0.40, 0.06, 0.18, 0.10]  # a full-length photo: a small face near the top
    crops = dict(source_crops(photo, face))
    assert set(crops) == {"source-face", "source-upper"}
    head = crops["source-face"]
    assert head.size[1] < 2000 * 0.35, "a close crop, not the whole photo"
    assert crops["source-upper"].size[1] > head.size[1]
    assert source_crops(photo, [0.0, 0.0, 0.95, 0.95]) == [], "not a plausible face box"
    assert source_crops(Image.new("RGB", (300, 300)), face) == [], "too small to train on"


def test_a_face_crop_frames_the_head_and_shoulders() -> None:
    """User, 2026-10-03: "the LoRA faces still aren't consistent". In a full-body
    training image at 512 px the face is about 50 px: the LoRA learns the outfit
    and a blur where the face is. A square 2.6x the face box, centred a little
    below the face, puts the same matching face at full size."""
    image = Image.new("RGB", (768, 1024))
    crop = face_crop(image, (330.0, 100.0, 120.0, 150.0))
    assert crop is not None and crop.size == (390, 390)
    edge = face_crop(image, (0.0, 0.0, 120.0, 150.0))
    assert edge is not None and edge.size == (390, 390), "clamped inside the image, not shrunk"
    assert face_crop(image, (330.0, 100.0, 60.0, 80.0)) is None, "208 px: too small to teach a face at 512"
    assert face_crop(image, (0.0, 0.0, 0.0, 0.0)) is None


def test_a_face_crop_is_captioned_as_a_close_up_of_its_view() -> None:
    assert face_crop_name("1790970581536-Raven-full-34-left") == "1790970581536-Raven-34-left-facecrop"
    assert face_crop_name("1790970347686-Raven-front-view") == "1790970347686-Raven-front-view-facecrop"
    assert face_crop_name("Raven-closeup-front") == "Raven-front-facecrop"
    florence = "A woman with dark hair."
    assert character_caption(florence, "rvnx", "0030-1790970581536-Raven-34-left-facecrop.png") == "rvnx, woman, close-up portrait, three-quarter view from the left"
    assert character_caption(florence, "rvnx", "Raven-high-facecrop.png") == "rvnx, woman, close-up portrait, high angle"
