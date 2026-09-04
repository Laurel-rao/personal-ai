---
name: video-quality-scorer
description: Score and accept or reject generated videos against an authoritative story contract using timestamped visual and audio evidence, a narrative veto gate, eight weighted quality dimensions, and deterministic JSON validation. Use when Codex needs to score, review,验收,打分,复评, compare, or decide whether to regenerate an AI-generated video, especially a scripted short film, Ref2VA result, MiniMax H3 output, or sequence whose plot order, causality, direction, dialogue, transition, characters, or required events must be preserved.
---

# Video Quality Scorer

## Source priority

Establish the authoritative story contract before scoring:

1. Use the user's latest explicit plot correction and required ending.
2. Use the approved screenplay or shot list.
3. Use the generation prompt only where it does not conflict with higher sources.

Never award story compliance merely because a video follows a prompt that already changed or omitted the approved plot.

For `六生六世 · 01A 战国`, read both the concise gate in [references/01a-warring-states-story-contract.md](references/01a-warring-states-story-contract.md) and the authoritative full text in [references/01a-warring-states-and-tang-full-story.md](references/01a-warring-states-and-tang-full-story.md) before inspecting the video. The full text wins if the concise gate ever drifts.

## Workflow

1. Verify the actual media file with `ffprobe`; record duration, resolution, frame rate, frame count, codecs, audio presence and checksum.
2. Convert the authoritative story into ordered critical beats. Record expected subject, action, direction, causality and transition for each beat.
3. Inspect the actual video at sufficient density. Use contact sheets for coverage, then extract original frames around every claimed event and boundary.
4. Directly listen to or transcribe required dialogue and sound events. If audio semantics cannot be verified, mark the related beat `unverified`; do not infer it from visuals or the prompt.
5. Complete the narrative veto gate before calculating quality points.
6. Score the eight dimensions only after the gate result is known.
7. Write `quality-score.json` and a concise `quality-score.md`, then run `scripts/validate_score.py` on the JSON.

## Narrative veto gate

Treat plot completeness, order and causality as acceptance prerequisites.

Set `story_gate.status` to `pass` only when every critical beat:

- is visibly or audibly present in the actual video;
- occurs in the required order;
- preserves specified character roles and screen directions;
- has a plausible causal connection to the next beat;
- reaches the required endpoint instead of stopping early or replacing it with another action.

Set the gate to `fail` when any critical beat is missing, reversed, assigned to the wrong character, directionally wrong, causally disconnected, or replaced by a conflicting event. Set it to `unverified` when required evidence cannot be inspected.

If the gate is not `pass`:

- set `score.final = min(score.raw, 49)`;
- set `score.decision = "regenerate"`;
- add `story_contract_failed` or `story_contract_unverified` to `score.caps_applied`;
- never claim the target score was reached, even when image quality, identity or technical delivery is excellent.

Do not average away a failed story. Visual polish cannot compensate for missing plot.

## Eight dimensions

Use these weights, totaling 100:

| Dimension | Weight | Rule |
| --- | ---: | --- |
| Story contract and shot compliance | 25 | Compare to the authoritative story, not just the submitted prompt. |
| Narrative and timeline | 15 | Check completeness, order, pacing and causality. |
| Character and reference consistency | 15 | Check identity, costume, role and continuity. |
| Visual quality | 15 | Check composition, exposure, detail, temporal stability and artifacts. |
| Action and camera | 10 | Check blocking, screen direction, shot-reverse-shot, motion and camera intent. |
| Anatomy and physical logic | 10 | Check body, props, contact, persistence and force. |
| Sound compliance | 5 | Check required dialogue, ambience, effects, continuity and loudness. |
| Technical compliance | 5 | Check file integrity and requested media specifications. |

Use 0-5 ratings and convert them proportionally to weighted points. Cite timestamps for every dimension. A story gate failure should normally produce low scores in the first two dimensions in addition to the final cap.

## Required JSON fields

Include:

- `story_contract.source` and `story_contract.summary`;
- `story_gate.status`, `story_gate.veto_applied`, and ordered `story_gate.beats`;
- for every beat: `id`, `requirement`, `status`, `evidence`, and timestamps when available;
- `score.raw`, `score.final`, `score.decision`, `score.confidence`, and `score.caps_applied`;
- exactly eight weighted dimensions totaling 100 points;
- `critical_issues` and an evidence-driven `prompt_revision`.

Never fabricate a timestamp, dialogue, sound event, URL, duration or score. Distinguish observed evidence from prompt intent.

## Decision bands

- `90-100` and story gate `pass`: accept.
- `80-89` and story gate `pass`: revise or regenerate according to defect repairability.
- `60-79` and story gate `pass`: regenerate.
- Story gate `fail` or `unverified`: regenerate, final score at most 49.

Do not submit a new generation unless the user has authorized generation or an active goal already includes repeated regeneration.
