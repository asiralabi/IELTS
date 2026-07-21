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
    "# Unsloth gives ~2x faster QLoRA. Two Kaggle-specific gotchas: (1) the free",
    "# Unsloth build trains on ONE GPU only, and (2) it needs a Turing-or-newer",
    "# card — use a **T4** (compute capability 7.5). The P100 is Pascal (6.0) and",
    "# has NO compiled Unsloth/Triton kernels -> 'no kernel image is available'.",
    "# Fit depends on the model AND the corpus length: the generator's records",
    "# are long (~5-7k tokens each), so it uses a 3B base; a 7B/14B OOMs a T4 at",
    "# train time on that corpus (see the generator's section 2 for the math).",
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
        "import os",
        "# Set BEFORE the torch/unsloth CUDA import. Lets the allocator grow",
        "# segments instead of failing on a large contiguous request — cheap VRAM",
        "# hygiene that reduces fragmentation-driven OOMs.",
        'os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"',
        "# Pin to ONE GPU. Unsloth's free build trains on a single GPU anyway, but",
        "# if TWO are visible (e.g. you picked 'T4 x2') it loads under an accelerate",
        "# device_map dispatch whose per-forward hooks pile extra tensors onto GPU 0",
        "# and OOM it. One visible GPU = clean single-device load. Set before import.",
        'os.environ["CUDA_VISIBLE_DEVICES"] = "0"',
        "",
        "import gc, sys, torch",
        "# ---- Dirty-kernel guard (the #1 cause of OOM in this notebook) ----------",
        "# If you re-run cells WITHOUT restarting, a previous run's model+optimizer",
        "# stay resident on the GPU and the next load stacks on top -> a misleading",
        "# CUDA OOM at trainer.train() even though the model fits fresh. Popping the",
        "# global names is NOT enough: IPython pins those GPU tensors through the",
        "# stored traceback of the previous OOM (sys.last_traceback holds every",
        "# frame's locals) and through the Out[]/_ output cache. Clear all of them,",
        "# then VERIFY the GPU is actually clean and fail fast with an actionable",
        "# message if it isn't — far better than a cryptic OOM five cells later.",
        'for _n in ("model", "tokenizer", "trainer", "trainer_stats", "dataset", "raw"):',
        "    globals().pop(_n, None)",
        "try:",
        "    _ip = get_ipython()",
        '    _ip.user_ns.get("Out", {}).clear()',
        '    for _v in ("_", "__", "___", "_i", "_ii", "_iii"):',
        "        _ip.user_ns.pop(_v, None)",
        "except Exception:",
        "    pass",
        "sys.last_type = sys.last_value = sys.last_traceback = None",
        "for _ in range(3):",
        "    gc.collect()",
        "    if torch.cuda.is_available():",
        "        torch.cuda.empty_cache()",
        "        torch.cuda.ipc_collect()",
        "",
        "if torch.cuda.is_available():",
        "    _free, _total = torch.cuda.mem_get_info()",
        "    _used = (_total - _free) / 1024**3",
        "    if _used > 2.0:",
        "        raise RuntimeError(",
        '            f"{_used:.1f} GiB is STILL resident on the GPU before loading — "',
        '            "this kernel is DIRTY (a previous run\'s model was not freed). "',
        '            "Fix: kernel menu -> \'Restart & Clear Cell Outputs\', then Run "',
        '            "All. Re-running cells without a restart stacks models on the "',
        '            "GPU and causes the misleading OOM at trainer.train()."',
        "        )",
        '    print(f"GPU clean: {_used:.2f} GiB resident before load — good to go.")',
        "",
        "from unsloth import FastLanguageModel",
        "",
        f'MODEL = "{model_repo}"',
        f"MAX_SEQ_LEN = {max_seq}",
        "",
        "model, tokenizer = FastLanguageModel.from_pretrained(",
        "    model_name=MODEL,",
        "    max_seq_length=MAX_SEQ_LEN,",
        "    dtype=None,          # auto: bf16 on Ampere+, fp16 on T4",
        "    load_in_4bit=True,   # QLoRA",
        "    # Pin the whole model to GPU 0: no cross-GPU sharding, and the model",
        "    # device matches the trainer device. A bnb 4-bit model loaded on a",
        "    # different device than the trainer makes accelerate raise ValueError",
        "    # ('can't train a model loaded in 4-bit precision on a different",
        "    # device...') at trainer.train(); this is the fix it recommends.",
        '    device_map={"": 0},',
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
        "",
        "# Guard against SILENT truncation. SFTTrainer cuts any sample longer than",
        "# MAX_SEQ_LEN, and because the assistant JSON (the training target) comes",
        "# LAST, truncation quietly destroys the label -> the model learns to emit",
        "# incomplete exams. Measure real token lengths and fail fast if any sample",
        "# would be cut, instead of training on corrupted targets.",
        "_lens = sorted(len(tokenizer(t, add_special_tokens=False)[\"input_ids\"])",
        "               for t in dataset[\"text\"])",
        "_over = [n for n in _lens if n > MAX_SEQ_LEN]",
        "print(f\"token lengths: min={_lens[0]} median={_lens[len(_lens)//2]} \"",
        "      f\"max={_lens[-1]} | MAX_SEQ_LEN={MAX_SEQ_LEN} | over={len(_over)}\")",
        "assert not _over, (",
        "    f\"{len(_over)} sample(s) exceed MAX_SEQ_LEN={MAX_SEQ_LEN} (max is \"",
        "    f\"{_lens[-1]}); they would be truncated and corrupt the target. \"",
        "    \"Raise MAX_SEQ_LEN (costs VRAM) or shorten those records.\")",
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
        "# 3) (optional) merged 16-bit HF weights for vLLM (~6 GB for 3B, ~14 GB for",
        "#    7B) — uncomment",
        "#    only if you have the disk / will push to the HF Hub.",
        f'# model.save_pretrained_merged("{out_lora}-merged16", tokenizer, save_method="merged_16bit")',
    )


# ---------------------------------------------------------------------------
# Generator notebook

generator = notebook([
    md(
        "# IELTS Listening — Generator QLoRA fine-tune (Kaggle)",
        "",
        "Fine-tunes **Qwen2.5-3B-Instruct** with **QLoRA / SFT** to generate the",
        "full doc contract from a spec:",
        "",
        "> Blueprint -> Dialogue -> Audio Performance Instructions -> Questions ->",
        "> Official Answers -> Accepted Variants -> Evaluation Metadata",
        "",
        "(the *Core Generator Model* + *Training Objective* of",
        "`AI IELTS Listening Exam Engine.md`).",
        "",
        "> ⚠️ **You MUST do a clean Restart & Run All** (kernel menu → *Restart &",
        "> Clear Cell Outputs*, then Run All — or a fresh *Save Version*). Do **not**",
        "> re-run single cells in a kernel that already trained: a prior run's model",
        "> stays resident on the GPU (IPython pins it via the last-error traceback +",
        "> output cache, so it can't be garbage-collected), the next load stacks on",
        "> top, and you get a misleading CUDA OOM at `trainer.train()` even though the",
        "> model fits fresh. **This was the real cause of the earlier OOMs** — a 3B",
        "> model was reported using 14 GiB because a 7B run was still resident. The",
        "> load cell now aggressively reclaims leftovers AND **hard-fails with a clear",
        "> message if the GPU isn't actually clean**, so a dirty kernel can't waste a",
        "> run silently. A true restart is still the reliable path (env-var GPU",
        "> pinning only applies before CUDA initialises).",
        "",
        "**Run cell 0 first** to clone the repo (it has the SFT datasets), then",
        "Run All.",
        "",
        "### Before you run",
        "1. Notebook settings: **Accelerator = GPU T4** (a *single* T4 — see below)",
        "   and **Internet = On** (needed for the clone + the Unsloth install).",
        "   Two traps: (a) **pick single *T4*, not *T4 x2***. Unsloth's free build",
        "   trains on one GPU, and if two are visible it loads under an accelerate",
        "   device_map dispatch that OOMs GPU 0 — the load cell now forces one GPU",
        "   via `CUDA_VISIBLE_DEVICES=0` as a guard, but pick single T4 anyway. And",
        "   (b) it needs a Turing+ card, so do **not** pick *P100*: it's Pascal",
        "   (compute capability 6.0), Unsloth/Triton have no kernels for it, and it",
        "   dies with `no kernel image is available for execution on the device`. So",
        "   **a single T4 is the target** — the generator's 3B base @ 8192 fits it",
        "   with headroom (7B and 14B both OOM on this long corpus; see section 2).",
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
    md("## 1. Load Qwen2.5-3B in 4-bit"),
    load_model_cell("unsloth/Qwen2.5-3B-Instruct-bnb-4bit", 8192),
    md(
        "## 2. Attach LoRA adapters",
        "",
        "The generator records are long and **uniformly** so — measured on the real",
        "corpus every record is 4.6k-6.9k tokens (a ~2.8k-token system prompt + the",
        "full exam JSON), median ~5.9k. So `MAX_SEQ_LEN` **must stay >= 7168** (8192",
        "is the safe value used here) or the assistant JSON gets truncated on the",
        "longest records and the model learns to emit incomplete exams. Do **not**",
        "lower it to save VRAM — and because the *shortest* record is already 4.6k,",
        "dropping the long samples doesn't help either (a 6144 cap keeps 185/241 but",
        "barely dents VRAM; a 4096 cap keeps 0).",
        "",
        "### Why 3B, not 7B or 14B",
        "The doc's Core Generator is nominally 14B, but on a Kaggle T4 (15 GB, the",
        "only usable free card — P100 is Pascal and can't run Unsloth) **neither 14B",
        "nor 7B fits this corpus**:",
        "- **14B** loads fine, then OOMs at the first attention forward in",
        "  `trainer.train()` (~40 MB short); `expandable_segments` can't recover it.",
        "- **7B** loads and even starts, then OOMs in the *backward* pass: on a",
        "  genuinely clean single-T4 run PyTorch holds ~14.3 GiB before a 2.79 GiB",
        "  attention-gradient alloc for a ~6.9k-token sample — ~2.7 GiB short, with",
        "  no fragmentation slack to reclaim. The O(seq^2) attention is the killer,",
        "  and since every sample is 5-7k tokens you can't shrink it without gutting",
        "  the corpus.",
        "",
        "So the generator uses **Qwen2.5-3B**, which keeps all 241 records at the",
        "full 8192 context (no truncation) and fits the T4 with headroom (~4 GiB",
        "freed vs 7B: a smaller 4-bit model plus a smaller attention matrix). If a",
        "clean run still OOMs, drop to `unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit`. To",
        "train 7B/14B instead, use a >=24 GB Turing+ GPU off-Kaggle (A10/L4/3090)",
        "and set `MODEL` back accordingly.",
    ),
    LORA,
    md("## 3. Load the SFT dataset"),
    data_cell("generator_sft.jsonl"),
    md("## 4. Train (response-only loss)"),
    trainer_cell(8192, 3, "qwen2.5-3b-ielts-generator-lora"),
    TRAIN,
    md("## 5. Save adapter + GGUF"),
    save_cell("qwen2.5-3b-ielts-generator-lora", "qwen2.5-3b-ielts-generator-gguf"),
    md(
        "## 6. Serve it, and point the backend at it",
        "",
        "**Option A — Ollama (local, CPU-friendly).** Unsloth writes the GGUF to a",
        "sibling `<name>_gguf/` folder (named after the BASE model) plus a ready",
        "`Modelfile`. Download that folder from the Kaggle output — for this run:",
        "```",
        "qwen2.5-3b-ielts-generator-gguf_gguf/",
        "  Qwen2.5-3B-Instruct.Q4_K_M.gguf   # quantised weights",
        "  Modelfile                          # generated by Unsloth (FROM preset)",
        "```",
        "Build the Ollama model from that Modelfile, or write your own (add the two",
        "PARAMETER lines for exam-JSON generation):",
        "```",
        "# Modelfile",
        "FROM ./Qwen2.5-3B-Instruct.Q4_K_M.gguf",
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
        "> ⚠️ **Do a clean Restart & Run All on a single T4** (not *T4 x2*, not",
        "> *P100* — see the generator notebook for why). The load cell hard-fails if",
        "> the kernel is dirty, so re-running cells without a restart won't silently",
        "> OOM at train time.",
        "",
        "### Before you run",
        "1. Notebook settings: **Accelerator = GPU T4** (a *single* T4) and",
        "   **Internet = On** (for the clone + the Unsloth install). Unlike the",
        "   generator, **7B fits comfortably here** — the evaluator's prompts are",
        "   short (<=1024 tokens), so there's no O(seq^2) attention blow-up.",
        "2. **Run cell 0 first** to `git clone` this repo — it brings",
        "   `backend/data/datasets/evaluator_sft.jsonl` (5989 records) with it. The",
        "   data cell also accepts a Kaggle Dataset named `ielts-listening-sft`.",
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
        "Unsloth writes the GGUF to a sibling `qwen2.5-7b-ielts-evaluator-gguf_gguf/`",
        "folder containing `Qwen2.5-7B-Instruct.Q4_K_M.gguf` + a ready `Modelfile`.",
        "Download that folder and build its own Ollama model:",
        "```",
        "ollama create ielts-evaluator -f Modelfile",
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
