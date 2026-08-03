# Fine-tuning the IELTS Exam Engine

This directory implements the fine-tuning half of `AI IELTS Listening Exam
Engine.md` — turning the hosted teacher model's behaviour into owned LoRA
checkpoints on **Qwen2.5-Instruct**. Each section gets a generator + evaluator
pair, built from the same templates:

| Model | Base | Job | Notebook |
|-------|------|-----|----------|
| **Generator** | Qwen2.5-3B-Instruct | spec → that section's full generation contract | `<section>_generator_qlora_kaggle.ipynb` |
| **Evaluator** | Qwen2.5-7B-Instruct | Question + Official Answer + Accepted Variants + Student Answer → verdict / reason / correct_answer / skill | `<section>_evaluator_qlora_kaggle.ipynb` |

The generator is **3B, not the 14B the doc nominally calls for**: on a Kaggle
T4 both 14B and 7B OOM at train time on a corpus of multi-thousand-token
records, and the GGUF has to generate at a usable rate on a CPU box. Each
generator notebook's section 2 carries the measured OOM math.

Sections currently built: **listening** and **reading**. Writing and Speaking
can have generators but *not* evaluators — the Cambridge PDFs contain no sample
answers, band scores, or examiner comments to train a marker on.

The design principle from the doc holds throughout: **never train on Cambridge
PDFs**. Everything is converted to structured JSON first, and the SFT targets
come from the teacher model's *original* generations (knowledge distillation),
not from copied Cambridge scripts.

## Why distillation, not copying Cambridge

The Cambridge book parser (`backend/app/ingest/cambridge_book.py`) extracts
question blocks and answer keys but **not** the listening audioscripts. It also
would be a copyright problem to train a generator on them. So:

- The **generator** learns from the hosted teacher (currently the NVIDIA-hosted
  `meta/llama-3.1-70b-instruct`, configured in `backend/.env`), whose outputs
  already match the doc's JSON contract. A 3B student distills that behaviour.
  `build_dataset.py` pins the teacher explicitly, so a `--generate` run can't
  accidentally call an already-installed fine-tune and train on its own output.
- The **evaluator** learns from real answer keys (both Cambridge and teacher),
  with correct / accepted-variant / incorrect student answers synthesised per
  question.

## Step 1 — build the datasets (on this machine)

```powershell
cd backend
# Export what's already in the DB:
python tools/build_dataset.py --section listening
python tools/build_dataset.py --section reading
# Grow the corpus with fresh teacher generations (recommended before training):
python tools/build_dataset.py --section listening --generate 40        # 40 single Parts
python tools/build_dataset.py --section listening --generate-tests 10  # 10 full 4-part tests
python tools/build_dataset.py --section reading --generate 40          # 40 practice sets
```

Outputs land in `backend/data/datasets/`, named for the exported section:

| File | Contents | Used by |
|------|----------|---------|
| `<section>_generator_sft.jsonl` | `{messages:[system,user,assistant]}`, assistant = that section's full generation contract | Generator notebook |
| `<section>_evaluator_sft.jsonl` | one record per (question, student answer) marking decision | Evaluator notebook |
| `cambridge_<section>.jsonl` | doc structured-JSON schema per Cambridge test + teacher unit (reference / audit) | — (documentation of the corpus) |

Cambridge prose is never a training target: rows the app served from a real
Cambridge test are excluded from the SFT files, and the `cambridge_*.jsonl`
records carry a null passage/dialogue body. Reading additionally drops
generator targets that contradict their own system prompt (fewer than 6
questions, or a passage under 550 words); each run reports the counts.

Each `--generate-*` run also **persists** the new material as
`GeneratedQuestion` rows, so the corpus compounds across runs and every export
picks it up. More data ⇒ better fine-tune; aim for a few hundred generator
records and a few thousand evaluator records before a serious run.

Generator targets are additionally gated by the *same* validator the live app
uses (`reading_trainer.validate_practice` / `listening_trainer.validate_part`),
so a set that reaches a student and a set that becomes a training target are
held to one standard.

> The `system` turn in each record is the real `<SECTION>_TRAINER_SYSTEM` /
> `<SECTION>_EVALUATOR_SYSTEM` prompt from `backend/app/llm/prompts.py`, so
> training conditions match inference exactly. **Editing a prompt changes every
> record**, so re-export before retraining.

## Step 2 — train on Kaggle (free T4 GPU)

1. Run **cell 0** in the notebook to `git clone` this repo (it carries the
   datasets). Needs a `GITHUB_TOKEN` Kaggle secret — the repo is private.
   Alternative: upload the `.jsonl` files as a Kaggle Dataset named
   `ielts-<section>-sft`; the data cell finds them either way.
2. Set **Accelerator = GPU T4** (a *single* T4, **not** T4 x2 and **not**
   P100 — P100 is Pascal and has no Unsloth kernels) and **Internet = On**.
3. Do a clean **Restart & Run All** of
   `<section>_generator_qlora_kaggle.ipynb`, then
   `<section>_evaluator_qlora_kaggle.ipynb`. Re-running cells in a kernel that
   already trained leaves the old model resident and causes a misleading OOM.
4. Each notebook saves a **LoRA adapter** and a **q4_k_m GGUF** to
   `/kaggle/working/` — download them from the notebook output. If the GGUF
   step dies on disk space, `gguf_export_kaggle.ipynb` redoes just that step
   from the saved adapter with intermediates in `/tmp`.

The notebooks use [Unsloth](https://github.com/unslothai/unsloth) for 4-bit
QLoRA and `train_on_responses_only`, so the model learns to *produce* exams
rather than echo the prompt.

## Step 3 — serve and point the backend at your models

Build each GGUF into an Ollama model using the tracked Modelfiles, then set the
per-task vars in `backend/.env`:

```powershell
ollama create ielts-generator -f finetune/Modelfile.generator
ollama create ielts-evaluator -f finetune/Modelfile.evaluator
```

```env
LLM_PROVIDER=ollama
GENERATOR_MODEL=ielts-generator
EVALUATOR_MODEL=ielts-evaluator
```

> Use the Modelfiles rather than Unsloth's exported one. Unsloth ships
> `PARAMETER temperature 1.5` and no `num_ctx`, which is wrong twice over here:
> the generator's output is a 5-6k-token JSON object that silently truncates at
> Ollama's default context, and an evaluator at 1.5 gives the same student
> answer a different verdict on each run. The tracked files set `num_ctx` to the
> notebook's `MAX_SEQ_LEN` and drop temperature to 0.4 (generator) / 0.1
> (marking). They also drop Unsloth's stock `SYSTEM "You are Qwen…"` line — the
> backend always sends its own system prompt.

Both are routed by `get_llm_client(task)` in `app/llm/client.py` and fall back
to the general model when blank. A configured fine-tune always routes to a
local Ollama client regardless of `LLM_PROVIDER`. For vLLM instead, serve the
merged weights and use `LLM_PROVIDER=openai` + `OPENAI_BASE_URL`.

> ⚠️ **`GENERATOR_MODEL` / `EVALUATOR_MODEL` are single globals, not
> per-section.** Listening's models are installed under those names today, so a
> reading fine-tune cannot be served alongside them without either (a)
> section-aware routing in `client.py`, or (b) training one multi-task LoRA on
> the concatenated per-section datasets. Option (b) needs no new code and no
> extra GGUFs on the CPU box; both corpora fit under 8192 tokens. **Not yet
> decided.**

## Files

- `<section>_generator_qlora_kaggle.ipynb` — generator fine-tune per section.
- `<section>_evaluator_qlora_kaggle.ipynb` — evaluator fine-tune per section.
- `gguf_export_kaggle.ipynb` — GGUF export from an already-trained adapter,
  for when the training run's export died on `/kaggle/working` disk space.
- `_build_notebooks.py` — regenerates every notebook from one `SectionCfg` per
  section (edit hyper-params there, then `python finetune/_build_notebooks.py`).
  Record counts in the prose are read from the built datasets at generation
  time so they can't go stale.
