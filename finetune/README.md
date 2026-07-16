# Fine-tuning the IELTS Listening Exam Engine

This directory implements the fine-tuning half of `AI IELTS Listening Exam
Engine.md` — turning the hosted teacher model's behaviour into two owned LoRA
checkpoints on **Qwen2.5-Instruct**:

| Model | Base | Job | Notebook |
|-------|------|-----|----------|
| **Generator** | Qwen2.5-14B-Instruct | spec → Blueprint, Dialogue, Audio Performance Instructions, Questions, Answers, Accepted Variants, Evaluation Metadata | `generator_qlora_kaggle.ipynb` |
| **Evaluator** | Qwen2.5-7B-Instruct | Question + Official Answer + Accepted Variants + Student Answer → verdict / reason / correct_answer / skill | `evaluator_qlora_kaggle.ipynb` |

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
  already match the doc's JSON contract. A 14B student distills that behaviour.
- The **evaluator** learns from real answer keys (both Cambridge and teacher),
  with correct / accepted-variant / incorrect student answers synthesised per
  question.

## Step 1 — build the datasets (on this machine)

```powershell
cd backend
# Export what's already in the DB:
python tools/build_dataset.py
# Grow the corpus with fresh teacher generations (recommended before training):
python tools/build_dataset.py --generate-parts 40      # 40 single Parts
python tools/build_dataset.py --generate-tests 10       # 10 full 4-part tests
```

Outputs land in `backend/data/datasets/`:

| File | Contents | Used by |
|------|----------|---------|
| `generator_sft.jsonl` | `{messages:[system,user,assistant]}`, assistant = full doc contract JSON | Generator notebook |
| `evaluator_sft.jsonl` | one record per (question, student answer) marking decision | Evaluator notebook |
| `cambridge_listening.jsonl` | doc structured-JSON schema per Cambridge + teacher Part (reference / audit) | — (documentation of the corpus) |

Each `--generate-*` run also **persists** the new material as
`GeneratedQuestion` rows, so the corpus compounds across runs and every export
picks it up. More data ⇒ better fine-tune; aim for a few hundred generator
records and a few thousand evaluator records before a serious run.

> The `system` turn in each record is the real `LISTENING_TRAINER_SYSTEM` /
> `EVALUATOR_SYSTEM` prompt from `backend/app/llm/prompts.py`, so training
> conditions match inference exactly.

## Step 2 — train on Kaggle (free T4/P100 GPU)

1. Zip/upload `backend/data/datasets/` as a **Kaggle Dataset** named
   `ielts-listening-sft` (both `.jsonl` files).
2. Open a notebook, **Add Data → your dataset**, set **Accelerator = GPU** and
   **Internet = On**.
3. Upload and run `generator_qlora_kaggle.ipynb`, then
   `evaluator_qlora_kaggle.ipynb`.
4. Each notebook saves a **LoRA adapter** and a **q4_k_m GGUF** to
   `/kaggle/working/` — download them from the notebook output.

The notebooks use [Unsloth](https://github.com/unslothai/unsloth) for 4-bit
QLoRA (fits 14B on one 16 GB T4) and `train_on_responses_only` so the model
learns to *produce* exams rather than echo the prompt.

## Step 3 — serve and point the backend at your models

**Generator (drop-in, no code change).** Serve the GGUF via Ollama and set in
`backend/.env`:

```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=ielts-generator
```

or serve merged weights on vLLM and use the OpenAI-compatible path
(`LLM_PROVIDER=openai`, `OPENAI_BASE_URL`, `OPENAI_MODEL`). `app/llm/client.py`
already supports both providers.

**Evaluator (needs a small addition).** The evaluator is a *separate* model.
Serve it as a second Ollama model (`ielts-evaluator`). Wiring it into marking is
a follow-up: add a second client that runs `EVALUATOR_SYSTEM` per answer and
feed the verdicts into `listening_trainer.check_full_test`. Until then, the
main model + `ANSWER_CHECKER_SYSTEM` continues to mark whole sets, so nothing
breaks.

## Files

- `generator_qlora_kaggle.ipynb` — generator fine-tune.
- `evaluator_qlora_kaggle.ipynb` — evaluator fine-tune.
- `_build_notebooks.py` — regenerates both notebooks (edit hyper-params here,
  then `python finetune/_build_notebooks.py`).
