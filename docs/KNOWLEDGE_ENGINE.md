# The knowledge engine

TFG remembers what happened when it rendered your shots, and tells you what
that history suggests. It does this from your own runs on your own machine.
Nothing is uploaded, nothing is shared between users, and the whole store is a
single file you can export, import or delete.

The design problem is not storage. It is honesty. "This model failed 4 of 5
renders" is arithmetic over a log. "This model overanimates static shots" is a
guess from a handful of examples. Presented the same way, the second borrows
the authority of the first. So the engine keeps three layers apart and never
lets a conclusion escape without the evidence behind it.

## Three layers

**Events** are what happened: a render finished, a version was approved, a
prompt was edited. They are appended and never rewritten. Each carries enough
context — model, provider, prompt, duration, error — to explain a conclusion
later.

**Observations** are what the events suggest. Each has a *kind*, and the kind
is the whole point:

| Kind | Means | Example |
|---|---|---|
| `fact` | Arithmetic over the log. Confidence 1.0 because the log is the source. | "Completed 8 of 9 renders here." |
| `observed_pattern` | A generalisation with enough runs behind it (≥ 5). | "Fails more often than it succeeds on this machine." |
| `user_preference` | A generalisation about *your* judgements (≥ 3 decisions). | "You usually keep what this model produces." |
| `model_recommendation` | A conclusion drawn from the above. Only when ≥ 5 runs, ≥ 80% success, and approvals ≥ rejections. | "A dependable default for this kind of shot." |
| `hypothesis` | The same generalisation, but from too small a sample to mean much. | "Fails more often than it succeeds" — from two runs. |

**Profiles** are the rolled-up view of one model: declared capabilities plus
observed behaviour plus its observations.

## Confidence

Every derived statement carries a confidence, computed as

```
confidence(n) = n / (n + 5)
```

Five runs buy 0.5, twenty buy 0.8, and nothing reaches 1.0. Experience raises
confidence; it does not create certainty. Only facts are stated at 1.0, because
a count is as reliable as the log it came from.

Confidence is never shown alone. The UI prints it beside the sample size, so
"80% confidence" cannot be read without also reading "20 observations".

## Prompt patterns

Alongside observations, the engine measures how individual pieces of prompt
vocabulary have fared with each model — "golden hour", "handheld", "extreme
close-up". It counts, it does not opine:

- The vocabulary is a fixed cinematic lexicon (shot sizes, camera moves, lens,
  lighting, look, motion). Free n-grams would surface "the" and whatever the
  subject of that particular shot was, which tells you nothing you can act on.
- A phrase's verdict is `worked` at ≥ 70% kept, `struggled` at ≤ 40%, and
  `unclear` below three judged uses. A phrase used twice gets no verdict at all.

## What is recorded, and how to stop it

Learning is on by default and can be switched off wholesale or by category in
**Settings → Knowledge**:

| Category | Covers |
|---|---|
| Renders | Which model ran, how long it took, whether it finished |
| Approvals | Which takes you kept, rejected or promoted |
| Edits | Prompt rewrites, model switches, continuity corrections |
| Ratings and notes | Anything you explicitly say about a result |

**The switch is honoured at write time, not at read time.** Turning learning
off stops collection; it does not merely hide what is still being gathered. A
call that would have recorded something returns `declined` rather than
pretending it succeeded.

Recording is also advisory in the strict sense: it happens outside the lock,
after the work is saved, wrapped so that a failure to remember something can
never fail the render or the edit that produced it.

## Where it lives

```
<outputs>/knowledge/knowledge.db
```

SQLite, not the JSON documents the rest of the app uses. The reason is the
access pattern rather than taste: this is an append-only log that grows with
every render and is read by aggregation. Rewriting a JSON array on every event
would be O(n) per write and would lose data on a crash mid-write. `sqlite3` is
in the standard library, so this adds a file, not a dependency or a service.
WAL mode lets the generation worker append while the UI reads.

The path is shown in Settings → Knowledge, so you can find it, back it up or
delete it yourself.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/knowledge` | Size, model count, database path, learning settings |
| `GET` | `/api/knowledge/models` | Every model used here, with observations and prompt patterns |
| `GET` | `/api/knowledge/events` | Recent events, optionally filtered by project |
| `PUT` | `/api/knowledge/settings` | Turn learning off wholesale or by category |
| `POST` | `/api/knowledge/feedback` | Record a rating or note; returns `declined` when that category is off |
| `POST` | `/api/knowledge/recommend` | Rank candidates the caller has already filtered by capability |
| `GET` | `/api/knowledge/export` | Portable dump (`schema_version: 1`) |
| `POST` | `/api/knowledge/import` | Merge another machine's export; refuses an unknown schema version |
| `POST` | `/api/knowledge/reset` | Forget everything, one model, or one project |

`recommend` only ranks what it is given — routing by capability stays with the
caller. It scores `(0.6 · success rate + 0.4 · approval rate) · confidence(n)`
and returns a reason that cites the evidence, so you can disagree with it. With
no history it says so plainly rather than inventing a preference.

## Code map

| File | Role |
|---|---|
| `backend/film/knowledge_models.py` | Events, observations, profiles, prompt patterns, learning settings |
| `backend/film/knowledge_store.py` | SQLite persistence, aggregation in SQL |
| `backend/handlers/knowledge_handler.py` | Recording, derivation rules, recommendation, export/import/reset |
| `backend/film/knowledge_api_types.py` | Request/response models |
| `backend/_routes/knowledge.py` | Routes |
| `frontend/types/knowledge.ts` | Mirror of the backend types (snake_case, no mapping layer) |
| `frontend/lib/knowledge-api.ts` | Typed client |
| `frontend/components/KnowledgeSettings.tsx` | Settings → Knowledge |
| `devtools/ui-mock/routes/knowledge.ts` | UI-only mock: the same derivation rules over a seeded log |

The hooks that feed it are in `handlers/film_generation_handler.py`
(`_finish_version` → `record_generation`) and `handlers/film_handler.py`
(`update_shot` and `promote_version` → `_record_judgement`). Both are attached
after construction via `attach_knowledge`, so the handlers keep working
unchanged if the engine is never attached.

## Tests

`backend/tests/test_knowledge.py` — 32 tests covering the confidence curve, the
recording path (including one that drives the real generation queue over HTTP
and asserts the queue actually reports), every derivation rule and its label,
the learning switches, declined feedback, export/import including a refused
schema version, reset by model and by project, and recommendation with and
without history.
