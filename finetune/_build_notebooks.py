"""Emit the two Kaggle QLoRA notebooks as valid .ipynb files.

Run:  python finetune/_build_notebooks.py
Regenerates generator_qlora_kaggle.ipynb and evaluator_qlora_kaggle.ipynb.
Kept in-repo so the notebooks are reproducible and easy to tweak in one place.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# GitHub repo the Kaggle notebooks clone to get the SFT datasets.
REPO_URL = "https://github.com/asiralabi/IELTS.git"


def md(*lines: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": _src(lines)}


def code(*lines: str) -> dict:
    return {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": _src(lines),
    }


def _src(lines: tuple[str, ...]) -> list[str]:
    text = "\n".join(lines)
    parts = text.split("\n")
    return [p + "\n" for p in parts[:-1]] + [parts[-1]]


def notebook(cells: list[dict]) -> dict:
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
            "accelerator": "GPU",
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


# ---------------------------------------------------------------------------
# Shared install / save / serve cells

INSTALL = code(
    "%%capture",
    "# Unsloth gives ~2x faster QLoRA and fits 4-bit 14B on a single 16 GB T4.",
    "# If this install ever breaks, follow the current Kaggle snippet at",
    "# https://github.com/unslothai/unsloth (the API used below is stable).",
    '!pip install -q "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"',
    "!pip install -q --no-deps trl peft accelerate bitsandbytes",
)


CLONE = code(
    "# Cell 0 — pull this repo so the SFT datasets are on the Kaggle filesystem.",
    "# This is a PRIVATE repo, so give Kaggle a token: Add-ons -> Secrets, add",
    "# GITHUB_TOKEN = a PAT with read access to the repo (fine-grained 'Contents:",
    "# read', or a classic token with the 'repo' scope).",
    "# Alternative: skip cloning and add the 'ielts-listening-sft' Kaggle Dataset;",
    "# the data cell below finds the jsonl either way.",
    "import os",
    f'REPO_URL = "{REPO_URL}"',
    "try:",
    "    from kaggle_secrets import UserSecretsClient",
    '    _tok = UserSecretsClient().get_secret("GITHUB_TOKEN")',
    '    REPO_URL = REPO_URL.replace("https://", f"https://{_tok}@")',
    "except Exception:",
    '    print("No GITHUB_TOKEN secret - trying anonymous clone "',
    '          "(only works if the repo is public).")',
    'if not os.path.isdir("ielts"):',
    "    !git clone --depth 1 $REPO_URL ielts",
    "!ls -lh ielts/backend/data/datasets/*.jsonl",
)


def load_model_cell(model_repo: str, max_seq: int) -> dict:
    return code(
        "from unsloth import FastLanguageModel",
        "import torch",
        "",
        f'MODEL = "{model_repo}"',
        f"MAX_SEQ_LEN = {max_seq}",
        "",
        "model, tokenizer = FastLanguageModel.from_pretrained(",
        "    model_name=MODEL,",
        "    max_seq_length=MAX_SEQ_LEN,",
        "    dtype=None,          # auto: bf16 on Ampere+, fp16 on T4",
        "    load_in_4bit=True,   # QLoRA",
        ")",
    )


LORA = code(
    "model = FastLanguageModel.get_peft_model(",
    "    model,",
    "    r=16,",
    "    target_modules=[\"q_proj\", \"k_proj\", \"v_proj\", \"o_proj\",",
    "                    \"gate_proj\", \"up_proj\", \"down_proj\"],",
    "    lora_alpha=16,",
    "    lora_dropout=0.0,",
    "    bias=\"none\",",
    "    use_gradient_checkpointing=\"unsloth\",   # long scripts -> save VRAM",
    "    random_state=3407,",
    ")",
)


def data_cell(filename: str) -> dict:
    return code(
        "import glob, os",
        "from datasets import load_dataset",
        "",
        "# Resolves the SFT jsonl produced by backend/tools/build_dataset.py.",
        "# Works whether you git-clone this repo into the notebook OR add it as a",
        "# Kaggle Dataset named 'ielts-listening-sft'.",
        f'FILENAME = "{filename}"',
        "CANDIDATES = [",
        '    f"/kaggle/input/ielts-listening-sft/{FILENAME}",',
        '    *glob.glob(f"/kaggle/**/backend/data/datasets/{FILENAME}", recursive=True),',
        '    *glob.glob(f"**/backend/data/datasets/{FILENAME}", recursive=True),',
        "]",
        "DATA_PATH = next((p for p in CANDIDATES if os.path.exists(p)), None)",
        "if DATA_PATH is None:",
        "    raise FileNotFoundError(",
        '        f"{FILENAME} not found. Git-clone this repo (see cell 0) or add the "',
        '        "Kaggle Dataset \'ielts-listening-sft\'.")',
        'print("Using dataset:", DATA_PATH)',
        "",
        "raw = load_dataset(\"json\", data_files=DATA_PATH, split=\"train\")",
        "",
        "def to_text(row):",
        "    # Each row is {\"messages\": [system, user, assistant]}; render with",
        "    # the model's own chat template so training matches inference.",
        "    return {\"text\": tokenizer.apply_chat_template(",
        "        row[\"messages\"], tokenize=False, add_generation_prompt=False)}",
        "",
        "dataset = raw.map(to_text, remove_columns=raw.column_names)",
        "print(dataset)",
        "print(dataset[0][\"text\"][:600])",
    )


def trainer_cell(max_seq: int, epochs: int, out_lora: str) -> dict:
    return code(
        "from trl import SFTTrainer, SFTConfig",
        "from unsloth.chat_templates import train_on_responses_only",
        "",
        "trainer = SFTTrainer(",
        "    model=model,",
        "    tokenizer=tokenizer,",
        "    train_dataset=dataset,",
        "    dataset_text_field=\"text\",",
        f"    max_seq_length={max_seq},",
        "    packing=False,",
        "    args=SFTConfig(",
        "        per_device_train_batch_size=1,",
        "        gradient_accumulation_steps=8,",
        "        warmup_steps=5,",
        f"        num_train_epochs={epochs},",
        "        learning_rate=2e-4,",
        "        fp16=not torch.cuda.is_bf16_supported(),",
        "        bf16=torch.cuda.is_bf16_supported(),",
        "        logging_steps=1,",
        "        optim=\"adamw_8bit\",",
        "        weight_decay=0.01,",
        "        lr_scheduler_type=\"linear\",",
        "        seed=3407,",
        f"        output_dir=\"{out_lora}-checkpoints\",",
        "        report_to=\"none\",",
        "    ),",
        ")",
        "",
        "# Mask the prompt: only the assistant JSON contributes to the loss, so",
        "# the model learns to PRODUCE exams, not to echo the spec/instructions.",
        "trainer = train_on_responses_only(",
        "    trainer,",
        "    instruction_part=\"<|im_start|>user\\n\",",
        "    response_part=\"<|im_start|>assistant\\n\",",
        ")",
    )


TRAIN = code("trainer_stats = trainer.train()", "print(trainer_stats)")


def save_cell(out_lora: str, out_gguf: str) -> dict:
    return code(
        "# 1) LoRA adapter only (tiny, ~100-300 MB) — load on top of the base.",
        f'model.save_pretrained("{out_lora}")',
        f'tokenizer.save_pretrained("{out_lora}")',
        "",
        "# 2) GGUF (q4_k_m) for llama.cpp / Ollama serving on CPU or small GPU.",
        "#    Merges + quantises; needs several GB of /kaggle/working disk.",
        f'model.save_pretrained_gguf("{out_gguf}", tokenizer, quantization_method="q4_k_m")',
        "",
        "# 3) (optional) merged 16-bit HF weights for vLLM. Large for 14B (~28 GB)",
        "#    — uncomment only if you have the disk / will push to the HF Hub.",
        f'# model.save_pretrained_merged("{out_lora}-merged16", tokenizer, save_method="merged_16bit")',
    )


# ---------------------------------------------------------------------------
# Generator notebook

generator = notebook([
    md(
        "# IELTS Listening — Generator QLoRA fine-tune (Kaggle)",
        "",
        "Fine-tunes **Qwen2.5-14B-Instruct** with **QLoRA / SFT** to generate the",
        "full doc contract from a spec:",
        "",
        "> Blueprint -> Dialogue -> Audio Performance Instructions -> Questions ->",
        "> Official Answers -> Accepted Variants -> Evaluation Metadata",
        "",
        "(the *Core Generator Model* + *Training Objective* of",
        "`AI IELTS Listening Exam Engine.md`).",
        "",
        "**Run cell 0 first** to clone the repo (it has the SFT datasets), then",
        "Run All.",
        "",
        "### Before you run",
        "1. Notebook settings: **Accelerator = GPU T4 x2** (or P100) and",
        "   **Internet = On** (needed for the clone + the Unsloth install).",
        "2. **Get the data** — run **cell 0** to `git clone` this repo (default), or",
        "   add `backend/data/datasets/generator_sft.jsonl` as a **Kaggle Dataset**",
        "   named `ielts-listening-sft`. Cell 3 locates the jsonl either way.",
        "",
        "The dataset is chat-format (`{messages:[system,user,assistant]}`); the",
        "assistant turn is the exact JSON the backend already parses, so the",
        "fine-tuned model is a drop-in for the hosted teacher.",
    ),
    md("## 0. Get the repo + datasets"),
    CLONE,
    INSTALL,
    md("## 1. Load Qwen2.5-14B in 4-bit"),
    load_model_cell("unsloth/Qwen2.5-14B-Instruct-bnb-4bit", 8192),
    md(
        "## 2. Attach LoRA adapters",
        "",
        "The generator records are long (~5-6k tokens each: a ~2.8k-token system",
        "prompt + the full exam JSON), so `MAX_SEQ_LEN` **must stay >= 6144** or the",
        "assistant JSON gets truncated and the model learns to emit incomplete",
        "exams. 8192 leaves clean headroom for the longest record.",
        "",
        "If you hit CUDA OOM, use **GPU T4 x2 / P100** (already recommended above)",
        "or switch `MODEL` to `unsloth/Qwen2.5-7B-Instruct-bnb-4bit` (the doc allows",
        "a smaller base) — but do **not** drop `MAX_SEQ_LEN` below 6144.",
    ),
    LORA,
    md("## 3. Load the SFT dataset"),
    data_cell("generator_sft.jsonl"),
    md("## 4. Train (response-only loss)"),
    trainer_cell(8192, 3, "qwen2.5-14b-ielts-generator-lora"),
    TRAIN,
    md("## 5. Save adapter + GGUF"),
    save_cell("qwen2.5-14b-ielts-generator-lora", "qwen2.5-14b-ielts-generator-gguf"),
    md(
        "## 6. Serve it, and point the backend at it",
        "",
        "**Option A — Ollama (local, CPU-friendly).** Download the GGUF, then:",
        "```",
        "# Modelfile",
        "FROM ./qwen2.5-14b-ielts-generator-gguf/unsloth.Q4_K_M.gguf",
        "PARAMETER temperature 0.4",
        "PARAMETER num_ctx 8192",
        "```",
        "```",
        "ollama create ielts-generator -f Modelfile",
        "```",
        "Then in `backend/.env`:",
        "```",
        "LLM_PROVIDER=ollama",
        "OLLAMA_MODEL=ielts-generator",
        "```",
        "",
        "**Option B — vLLM (GPU, OpenAI-compatible).** Serve the merged weights",
        "(or base + adapter) and set:",
        "```",
        "LLM_PROVIDER=openai",
        "OPENAI_BASE_URL=http://<host>:8000/v1",
        "OPENAI_MODEL=ielts-generator",
        "OPENAI_API_KEY=dummy",
        "```",
        "No app code changes are needed — `app/llm/client.py` already speaks both.",
    ),
])

# ---------------------------------------------------------------------------
# Evaluator notebook

evaluator = notebook([
    md(
        "# IELTS Listening — Evaluator QLoRA fine-tune (Kaggle)",
        "",
        "Fine-tunes the doc's **separate evaluator** (a Qwen2.5-**7B**-Instruct",
        "LoRA — the doc permits 7B here for efficiency) to judge one answer at a",
        "time:",
        "",
        "> Input: Question + Official Answer + Accepted Variants + Student Answer",
        "> Output: verdict / reason / correct_answer / skill",
        "",
        "### Before you run",
        "1. `cd backend && python tools/build_dataset.py` -> produces",
        "   `data/datasets/evaluator_sft.jsonl`.",
        "2. Upload it in the same Kaggle Dataset (`ielts-listening-sft`).",
        "3. Accelerator = **GPU T4** (7B fits comfortably); Internet = On.",
    ),
    md("## 0. Get the repo + datasets"),
    CLONE,
    INSTALL,
    md("## 1. Load Qwen2.5-7B in 4-bit"),
    load_model_cell("unsloth/Qwen2.5-7B-Instruct-bnb-4bit", 1024),
    md("## 2. Attach LoRA adapters"),
    LORA,
    md(
        "## 3. Load the SFT dataset",
        "",
        "Evaluator prompts are short, so `MAX_SEQ_LEN=1024` is plenty and keeps",
        "training fast.",
    ),
    data_cell("evaluator_sft.jsonl"),
    md("## 4. Train (response-only loss)"),
    trainer_cell(1024, 2, "qwen2.5-7b-ielts-evaluator-lora"),
    TRAIN,
    md("## 5. Save adapter + GGUF"),
    save_cell("qwen2.5-7b-ielts-evaluator-lora", "qwen2.5-7b-ielts-evaluator-gguf"),
    md(
        "## 6. Serve it as a second model",
        "",
        "Serve the GGUF as its own Ollama model:",
        "```",
        "ollama create ielts-evaluator -f Modelfile   # FROM the evaluator GGUF",
        "```",
        "The evaluator is a **separate** model from the generator, so using it",
        "for marking needs a small backend addition: a second client pointed at",
        "`ielts-evaluator` that runs the `EVALUATOR_SYSTEM` prompt",
        "(`app/llm/prompts.py`) per answer, feeding results into",
        "`listening_trainer.check_full_test`. Until that wiring lands, the base",
        "model + `ANSWER_CHECKER_SYSTEM` continues to mark whole sets. The",
        "system prompt this model was trained on lives in `EVALUATOR_SYSTEM`.",
    ),
])

(HERE / "generator_qlora_kaggle.ipynb").write_text(
    json.dumps(generator, indent=1, ensure_ascii=False), encoding="utf-8"
)
(HERE / "evaluator_qlora_kaggle.ipynb").write_text(
    json.dumps(evaluator, indent=1, ensure_ascii=False), encoding="utf-8"
)
print("wrote generator_qlora_kaggle.ipynb and evaluator_qlora_kaggle.ipynb")
