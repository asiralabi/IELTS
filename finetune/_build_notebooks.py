"""Emit the Kaggle QLoRA notebooks as valid .ipynb files.

Run:  python finetune/_build_notebooks.py
Regenerates a generator + evaluator notebook per section, plus the standalone
GGUF-export notebook. Kept in-repo so the notebooks are reproducible and easy
to tweak in one place.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATASETS = HERE.parent / "backend" / "data" / "datasets"

# GitHub repo the Kaggle notebooks clone to get the SFT datasets.
REPO_URL = "https://github.com/asiralabi/IELTS.git"


@dataclass(frozen=True)
class SectionCfg:
    """Everything that differs between one section's notebooks and another's.

    Artifact names are section-scoped for every section EXCEPT listening, whose
    names are pinned by the already-deployed `backend/.env` (GENERATOR_MODEL /
    EVALUATOR_MODEL) and the Ollama models built from them. Renaming those
    would break a working install for no gain.
    """

    section: str
    title: str
    gen_max_seq: int
    gen_lora: str
    ollama_gen: str
    ollama_eval: str
    contract: tuple[str, ...]
    contract_doc: str
    seq_rationale: tuple[str, ...]
    serve_caveat: tuple[str, ...] = ()
    # Which sections' datasets this model trains on. Empty = just its own;
    # more than one makes it a multi-task model over the concatenated corpora.
    parts: tuple[str, ...] = ()

    @property
    def sources(self) -> tuple[str, ...]:
        return self.parts or (self.section,)

    @property
    def kaggle_ds(self) -> str:
        return f"ielts-{self.section}-sft"

    @property
    def gen_files(self) -> tuple[str, ...]:
        return tuple(f"{s}_generator_sft.jsonl" for s in self.sources)

    @property
    def eval_files(self) -> tuple[str, ...]:
        return tuple(f"{s}_evaluator_sft.jsonl" for s in self.sources)

    @property
    def gen_gguf(self) -> str:
        return self.gen_lora.replace("-lora", "-gguf")

    @property
    def eval_lora(self) -> str:
        return self.gen_lora.replace("qwen2.5-3b", "qwen2.5-7b").replace(
            "-generator-lora", "-evaluator-lora"
        )

    @property
    def eval_gguf(self) -> str:
        return self.eval_lora.replace("-lora", "-gguf")


def record_count(filenames: tuple[str, ...]) -> int:
    """Total records across built SFT files; missing files count as zero.

    Read at build time on purpose: these counts appear in the notebook prose,
    and hardcoding them silently went stale once already (the listening
    generator said 241 long after a re-export dropped it to 225).
    """
    total = 0
    for name in filenames:
        path = DATASETS / name
        if path.exists():
            with path.open(encoding="utf-8") as fh:
                total += sum(1 for line in fh if line.strip())
    return total


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


def clone_cell(kaggle_ds: str) -> dict:
    return code(
    "# Cell 0 — pull this repo so the SFT datasets are on the Kaggle filesystem.",
    "# This is a PRIVATE repo, so give Kaggle a token: Add-ons -> Secrets, add",
    "# GITHUB_TOKEN = a PAT with read access to the repo (fine-grained 'Contents:",
    "# read', or a classic token with the 'repo' scope).",
    f"# Alternative: skip cloning and add the '{kaggle_ds}' Kaggle Dataset;",
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


def data_cell(filenames: tuple[str, ...], kaggle_ds: str) -> dict:
    return code(
        "import glob, os",
        "from datasets import load_dataset",
        "",
        "# Resolves the SFT jsonl(s) produced by backend/tools/build_dataset.py.",
        "# Works whether you git-clone this repo into the notebook OR add it as a",
        f"# Kaggle Dataset named '{kaggle_ds}'.",
        "# More than one filename = a multi-task corpus; the records are simply",
        "# concatenated. Each carries its own section's system prompt, so the model",
        "# learns to condition on it rather than blending the contracts.",
        f"FILENAMES = {list(filenames)!r}",
        "",
        "def _resolve(name):",
        "    for cand in [",
        f'        f"/kaggle/input/{kaggle_ds}/{{name}}",',
        '        *glob.glob(f"/kaggle/**/backend/data/datasets/{name}", recursive=True),',
        '        *glob.glob(f"**/backend/data/datasets/{name}", recursive=True),',
        "    ]:",
        "        if os.path.exists(cand):",
        "            return cand",
        "    raise FileNotFoundError(",
        '        f"{name} not found. Git-clone this repo (see cell 0) or add the "',
        f'        "Kaggle Dataset \'{kaggle_ds}\'.")',
        "",
        "DATA_PATHS = [_resolve(n) for n in FILENAMES]",
        'print("Using dataset(s):", *DATA_PATHS, sep="\\n  ")',
        "",
        "raw = load_dataset(\"json\", data_files=DATA_PATHS, split=\"train\")",
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


def _gguf_export_lines(out_gguf: str) -> list[str]:
    # Disk-safe GGUF (q4_k_m) export. Shared by the training notebooks' save
    # cell AND the standalone conversion notebook.
    return [
        "# The GGUF path writes a merged fp16 model, then an F16 GGUF, then the",
        "# q4_k_m — transiently ~2x the model size (a 7B needs ~30 GB). Writing",
        "# those into /kaggle/working (~20 GB quota) overflows it and dies with",
        "# 'OSError: Not enough free space'. So send every intermediate to /tmp",
        "# (the container's larger scratch) and copy back ONLY the final ~4.7 GB",
        "# quantised GGUF + Modelfile.",
        "import os, glob, shutil",
        "",
        '_TMP = "/tmp/_gguf_export"',
        "if os.path.isdir(_TMP):",
        "    shutil.rmtree(_TMP)",
        'model.save_pretrained_gguf(_TMP, tokenizer, quantization_method="q4_k_m")',
        "",
        "# Unsloth writes the GGUF into a sibling '<dir>_gguf/' folder. Copy only",
        "# the quantised file — never the ~15 GB F16 intermediate, if it lingers.",
        '_SRC = _TMP + "_gguf"',
        f'_DST = "/kaggle/working/{out_gguf}_gguf"',
        "os.makedirs(_DST, exist_ok=True)",
        '_all = glob.glob(f"{_SRC}/*.gguf")',
        '_keep = [p for p in _all if "q4_k_m" in os.path.basename(p).lower()] or _all',
        '_keep += glob.glob(f"{_SRC}/Modelfile")',
        "for _f in _keep:",
        "    shutil.copy(_f, _DST)",
        '    print("kept", os.path.basename(_f), f"({os.path.getsize(_f)/1024**3:.2f} GiB)")',
        '_final = glob.glob(f"{_DST}/*.gguf")',
        'assert _final, "no GGUF produced — check the conversion log above"',
        'print("Final GGUF folder:", _DST, "->", [os.path.basename(p) for p in _final])',
    ]


def save_cell(out_lora: str, out_gguf: str) -> dict:
    return code(*([
        "# 1) LoRA adapter only (tiny, ~100-300 MB) — load on top of the base later.",
        f'model.save_pretrained("{out_lora}")',
        f'tokenizer.save_pretrained("{out_lora}")',
        "",
        "# 2) Quantised GGUF for llama.cpp / Ollama (disk-safe: intermediates -> /tmp).",
    ] + _gguf_export_lines(out_gguf) + [
        "",
        "# 3) (optional) merged 16-bit HF weights for vLLM (~6 GB for 3B, ~14 GB for",
        "#    7B) — uncomment only if you have the disk / will push to the HF Hub.",
        f'# model.save_pretrained_merged("{out_lora}-merged16", tokenizer, save_method="merged_16bit")',
    ]))


def load_adapter_cell(max_seq: int) -> dict:
    return code(
        "import os",
        'os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"',
        'os.environ["CUDA_VISIBLE_DEVICES"] = "0"',
        "",
        "import glob",
        "from unsloth import FastLanguageModel",
        "",
        "# Find the trained LoRA adapter you attached as an input (Add Input ->",
        "# Notebook Output -> the training run). We locate the folder that holds",
        "# adapter_config.json anywhere under /kaggle/input.",
        '_cfgs = glob.glob("/kaggle/input/**/adapter_config.json", recursive=True)',
        "if not _cfgs:",
        "    raise FileNotFoundError(",
        "        \"No adapter found under /kaggle/input. Add the training run's \"",
        '        "OUTPUT as an input: Add Input -> Notebook Output -> pick the run "',
        '        "that saved the *-lora folder, then re-run.")',
        "ADAPTER_DIR = os.path.dirname(_cfgs[0])",
        'print("Using adapter:", ADAPTER_DIR)',
        "",
        f"MAX_SEQ_LEN = {max_seq}",
        "# Point from_pretrained at the ADAPTER dir; Unsloth reads its base model",
        "# from adapter_config.json, downloads it (needs Internet=On), and applies",
        "# the trained LoRA. No get_peft_model here — the adapter is already trained.",
        "model, tokenizer = FastLanguageModel.from_pretrained(",
        "    model_name=ADAPTER_DIR,",
        "    max_seq_length=MAX_SEQ_LEN,",
        "    dtype=None,",
        "    load_in_4bit=True,",
        '    device_map={"": 0},',
        ")",
    )


# ---------------------------------------------------------------------------
# Generator notebook

def generator_notebook(cfg: SectionCfg) -> dict:
    return notebook([
    md(
        f"# IELTS {cfg.title} — Generator QLoRA fine-tune (Kaggle)",
        "",
        "Fine-tunes **Qwen2.5-3B-Instruct** with **QLoRA / SFT** to generate the",
        "full doc contract from a spec:",
        "",
        *cfg.contract,
        "",
        "(the *Core Generator Model* + *Training Objective* of",
        f"`{cfg.contract_doc}`).",
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
        f"   **a single T4 is the target** — the generator's 3B base @ {cfg.gen_max_seq} fits",
        "   it with headroom (7B and 14B both OOM on this corpus; see section 2).",
        "2. **Get the data** — run **cell 0** to `git clone` this repo (default), or",
        f"   add {', '.join(f'`{f}`' for f in cfg.gen_files)} as a **Kaggle Dataset**",
        f"   named `{cfg.kaggle_ds}`. Cell 3 locates the jsonl either way.",
        "",
        "The dataset is chat-format (`{messages:[system,user,assistant]}`); the",
        "assistant turn is the exact JSON the backend already parses, so the",
        "fine-tuned model is a drop-in for the hosted teacher.",
    ),
    md("## 0. Get the repo + datasets"),
    clone_cell(cfg.kaggle_ds),
    INSTALL,
    md("## 1. Load Qwen2.5-3B in 4-bit"),
    load_model_cell("unsloth/Qwen2.5-3B-Instruct-bnb-4bit", cfg.gen_max_seq),
    md(
        "## 2. Attach LoRA adapters",
        "",
        *cfg.seq_rationale,
    ),
    LORA,
    md("## 3. Load the SFT dataset"),
    data_cell(cfg.gen_files, cfg.kaggle_ds),
    md("## 4. Train (response-only loss)"),
    trainer_cell(cfg.gen_max_seq, 3, cfg.gen_lora),
    TRAIN,
    md("## 5. Save adapter + GGUF"),
    save_cell(cfg.gen_lora, cfg.gen_gguf),
    md(
        "## 6. Serve it, and point the backend at it",
        "",
        "**Option A — Ollama (local, CPU-friendly).** Unsloth writes the GGUF to a",
        "sibling `<name>_gguf/` folder (named after the BASE model) plus a ready",
        "`Modelfile`. Download that folder from the Kaggle output — for this run:",
        "```",
        f"{cfg.gen_gguf}_gguf/",
        "  Qwen2.5-3B-Instruct.Q4_K_M.gguf   # quantised weights",
        "  Modelfile                          # generated by Unsloth (FROM preset)",
        "```",
        "Build the Ollama model from that Modelfile, or write your own (add the two",
        "PARAMETER lines for exam-JSON generation):",
        "```",
        "# Modelfile",
        "FROM ./Qwen2.5-3B-Instruct.Q4_K_M.gguf",
        "PARAMETER temperature 0.4",
        f"PARAMETER num_ctx {cfg.gen_max_seq}",
        "```",
        "```",
        f"ollama create {cfg.ollama_gen} -f Modelfile",
        "```",
        "Then in `backend/.env`:",
        "```",
        "LLM_PROVIDER=ollama",
        f"GENERATOR_MODEL={cfg.ollama_gen}",
        "```",
        "",
        "**Option B — vLLM (GPU, OpenAI-compatible).** Serve the merged weights",
        "(or base + adapter) and set:",
        "```",
        "LLM_PROVIDER=openai",
        "OPENAI_BASE_URL=http://<host>:8000/v1",
        f"OPENAI_MODEL={cfg.ollama_gen}",
        "OPENAI_API_KEY=dummy",
        "```",
        "No app code changes are needed — `app/llm/client.py` already speaks both.",
        *cfg.serve_caveat,
    ),
])

# ---------------------------------------------------------------------------
# Evaluator notebook

def evaluator_notebook(cfg: SectionCfg) -> dict:
    return notebook([
    md(
        f"# IELTS {cfg.title} — Evaluator QLoRA fine-tune (Kaggle)",
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
        f"   {', '.join(f'`{f}`' for f in cfg.eval_files)}",
        f"   ({record_count(cfg.eval_files)} records) with it. The data cell also",
        f"   accepts a Kaggle Dataset named `{cfg.kaggle_ds}`.",
    ),
    md("## 0. Get the repo + datasets"),
    clone_cell(cfg.kaggle_ds),
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
    data_cell(cfg.eval_files, cfg.kaggle_ds),
    md("## 4. Train (response-only loss)"),
    trainer_cell(1024, 2, cfg.eval_lora),
    TRAIN,
    md("## 5. Save adapter + GGUF"),
    save_cell(cfg.eval_lora, cfg.eval_gguf),
    md(
        "## 6. Serve it as a second model",
        "",
        f"Unsloth writes the GGUF to a sibling `{cfg.eval_gguf}_gguf/`",
        "folder containing `Qwen2.5-7B-Instruct.Q4_K_M.gguf` + a ready `Modelfile`.",
        "Download that folder and build its own Ollama model:",
        "```",
        f"ollama create {cfg.ollama_eval} -f Modelfile",
        "```",
        "Then point the backend's evaluator task at it in `backend/.env`:",
        "```",
        f"EVALUATOR_MODEL={cfg.ollama_eval}",
        "```",
        "The evaluator is a **separate** model from the generator; `get_llm_client",
        '("evaluator")` in `app/llm/client.py` routes per-answer marking to it and',
        "falls back to the general model when the var is blank. The system prompt",
        "this model was trained on lives in `EVALUATOR_SYSTEM` (`app/llm/prompts.py`).",
    ),
])

# ---------------------------------------------------------------------------
# Standalone GGUF-export notebook (no retrain) — for when a training run
# finished (adapter saved) but the GGUF step ran out of /kaggle/working disk.

conversion = notebook([
    md(
        "# IELTS — GGUF export from a trained adapter (Kaggle, disk-safe)",
        "",
        "Use this when a training run **finished** — the LoRA adapter saved — but",
        "the GGUF step died with `OSError: Not enough free space`. Unsloth's merge",
        "+ F16 intermediates need ~30 GB for a 7B, over the ~20 GB",
        "`/kaggle/working` quota. This notebook **does not retrain**: it loads your",
        "saved adapter, then runs the export with every intermediate redirected to",
        "`/tmp`, copying only the final ~4.7 GB quantised GGUF back into",
        "`/kaggle/working`.",
        "",
        "### Before you run",
        "1. **Attach the trained adapter:** *Add Input → Notebook Output →* the run",
        "   that saved `qwen2.5-7b-ielts-evaluator-lora` (your evaluator training",
        "   run). It mounts under `/kaggle/input/…`; cell 2 finds it by searching",
        "   for `adapter_config.json`, so any adapter works — not just the",
        "   evaluator's.",
        "2. **Accelerator = a single GPU T4**, **Internet = On** (the base model is",
        "   downloaded to merge against). *P100 won't run Unsloth* — see the",
        "   training notebooks for why.",
        "3. Run All. The output folder `qwen2.5-7b-ielts-evaluator-gguf_gguf/` will",
        "   hold `Qwen2.5-7B-Instruct.Q4_K_M.gguf` + a ready `Modelfile`.",
        "",
        "> If the adapter isn't in the previous run's output (e.g. the disk filled",
        "> before it saved), fall back to re-running the evaluator notebook end to",
        "> end — its save cell is now disk-safe too.",
    ),
    md("## 0. Install Unsloth"),
    INSTALL,
    md("## 1. Load the base + your trained adapter"),
    load_adapter_cell(1024),
    md("## 2. Export GGUF (intermediates → /tmp, final → working)"),
    code(*_gguf_export_lines("qwen2.5-7b-ielts-evaluator-gguf")),
    md(
        "## 3. Serve it",
        "",
        "Download `qwen2.5-7b-ielts-evaluator-gguf_gguf/` from the output, then:",
        "```",
        "ollama create ielts-evaluator -f Modelfile",
        "```",
        "This is the **evaluator** (a separate model from the generator). Wiring it",
        "into per-answer marking still needs the small backend addition described",
        "in the evaluator notebook's section 6 (`EVALUATOR_SYSTEM` in",
        "`app/llm/prompts.py`).",
    ),
])

# ---------------------------------------------------------------------------
# Section configs

LISTENING = SectionCfg(
    section="listening",
    title="Listening",
    gen_max_seq=8192,
    # Not section-scoped like Reading's: these names are already baked into the
    # deployed backend/.env and the Ollama models built from them.
    gen_lora="qwen2.5-3b-ielts-generator-lora",
    ollama_gen="ielts-generator",
    ollama_eval="ielts-evaluator",
    contract=(
        "> Blueprint -> Dialogue -> Audio Performance Instructions -> Questions ->",
        "> Official Answers -> Accepted Variants -> Evaluation Metadata",
    ),
    contract_doc="AI IELTS Listening Exam Engine.md",
    seq_rationale=(
        "The generator records are long and **uniformly** so — measured on the real",
        "corpus every record is 4.6k-6.3k tokens (a ~2.8k-token system prompt + the",
        "full exam JSON), median ~5.3k. So `MAX_SEQ_LEN` **must stay >= 7168** (8192",
        "is the safe value used here) or the assistant JSON gets truncated on the",
        "longest records and the model learns to emit incomplete exams. Do **not**",
        "lower it to save VRAM — and because the *shortest* record is already 4.6k,",
        "dropping the long samples doesn't help either (a 4096 cap keeps 0 records).",
        "",
        "### Why 3B, not 7B or 14B",
        "The doc's Core Generator is nominally 14B, but on a Kaggle T4 (15 GB, the",
        "only usable free card — P100 is Pascal and can't run Unsloth) **neither 14B",
        "nor 7B fits this corpus**:",
        "- **14B** loads fine, then OOMs at the first attention forward in",
        "  `trainer.train()` (~40 MB short); `expandable_segments` can't recover it.",
        "- **7B** loads and even starts, then OOMs in the *backward* pass: on a",
        "  genuinely clean single-T4 run PyTorch holds ~14.3 GiB before a 2.79 GiB",
        "  attention-gradient alloc for a ~6.3k-token sample — ~2.7 GiB short, with",
        "  no fragmentation slack to reclaim. The O(seq^2) attention is the killer,",
        "  and since every sample is 4.6-6.3k tokens you can't shrink it without",
        "  gutting the corpus.",
        "",
        "So the generator uses **Qwen2.5-3B**, which keeps every record at the full",
        "8192 context (no truncation) and fits the T4 with headroom (~4 GiB freed vs",
        "7B: a smaller 4-bit model plus a smaller attention matrix). If a clean run",
        "still OOMs, drop to `unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit`. To train",
        "7B/14B instead, use a >=24 GB Turing+ GPU off-Kaggle (A10/L4/3090) and set",
        "`MODEL` back accordingly.",
    ),
)

READING = SectionCfg(
    section="reading",
    title="Reading",
    # Reading records top out ~4.6k (see below), so 8192 would just waste VRAM.
    gen_max_seq=6144,
    gen_lora="qwen2.5-3b-ielts-reading-generator-lora",
    ollama_gen="ielts-reading-generator",
    ollama_eval="ielts-reading-evaluator",
    contract=(
        "> Passage -> Questions (13 official Academic Reading types) ->",
        "> Options -> Official Answers -> Word Limits",
    ),
    contract_doc="AI IELTS Instructor & Examiner.pdf",
    seq_rationale=(
        "Reading records are long but **shorter and tighter than Listening's**:",
        "measured on the real corpus they run 3.1k-4.6k tokens, median ~3.7k. The",
        "passage is ~700 words, but unlike Listening there is no `audio_script`,",
        "no speaker list, no blueprint and no `accepted_variants`/`answer_positions`",
        "block, so a record costs ~30% fewer tokens.",
        "",
        "`MAX_SEQ_LEN` is therefore **6144**, not Listening's 8192 — comfortably",
        "above the longest record with room for the corpus to grow, while saving",
        "VRAM on the O(seq^2) attention. The data cell hard-fails if any record",
        "would actually be truncated, so raise this rather than let it cut: the",
        "assistant JSON is last, and truncating it teaches the model to emit",
        "incomplete exams.",
        "",
        "### Why 3B",
        "Same T4 constraint as the Listening generator (see that notebook for the",
        "full OOM math: 14B dies at the first attention forward, 7B in the backward",
        "pass). Reading's shorter records give more slack, but the deciding factor",
        "is serving, not training — the GGUF runs on a CPU box, where a 3B q4",
        "(~1.9 GB) generates at a usable rate and a 7B q4 (~4.7 GB) does not.",
    ),
    serve_caveat=(
        "",
        "> ⚠️ **`GENERATOR_MODEL` is a single global, not per-section.** Setting it",
        "> to `ielts-reading-generator` routes *every* generator call to this model,",
        "> including Listening's. Serving both at once needs one of two changes,",
        "> neither of which has been made yet:",
        "> 1. **Section-aware routing** — extend `get_llm_client(task)` in",
        ">    `app/llm/client.py` to take a section and read",
        ">    `READING_GENERATOR_MODEL` / `LISTENING_GENERATOR_MODEL`. Costs 4 GGUFs",
        ">    resident (~13 GB) on the CPU box.",
        "> 2. **One multi-task generator** — train a single LoRA on the concatenated",
        ">    `listening_generator_sft.jsonl` + `reading_generator_sft.jsonl`. Both",
        ">    corpora fit under 8192 tokens, so this needs no new infrastructure and",
        ">    keeps `GENERATOR_MODEL=ielts-generator` as-is.",
        "",
        "Until one of those lands, train and evaluate this model, but expect to flip",
        "`GENERATOR_MODEL` back to `ielts-generator` before using Listening.",
    ),
)

COMBINED = SectionCfg(
    section="combined",
    title="Listening + Reading (multi-task)",
    # Must clear the LONGEST record across both corpora — listening's 6343.
    gen_max_seq=8192,
    gen_lora="qwen2.5-3b-ielts-multitask-generator-lora",
    # The whole point: these are the names already in backend/.env, so a
    # multi-task model is a drop-in with no routing change and no extra GGUFs.
    ollama_gen="ielts-generator",
    ollama_eval="ielts-evaluator",
    parts=("listening", "reading"),
    contract=(
        "> Listening: Blueprint -> Dialogue -> Audio Performance Instructions ->",
        "> Questions -> Official Answers -> Accepted Variants -> Evaluation Metadata",
        ">",
        "> Reading: Passage -> Questions (13 official Academic Reading types) ->",
        "> Options -> Official Answers -> Word Limits",
    ),
    contract_doc="AI IELTS Listening Exam Engine.md",
    seq_rationale=(
        "This model trains on **both** sections' generator corpora concatenated.",
        "That works without any special handling because each record carries its",
        "own section's system prompt (`LISTENING_TRAINER_SYSTEM` or",
        "`READING_TRAINER_SYSTEM`) as its `system` turn — so the model learns to",
        "*condition on the prompt* rather than blending the two contracts. It is",
        "ordinary multi-task instruction tuning, and it matches inference exactly,",
        "since the backend sends the same system prompt per section.",
        "",
        "`MAX_SEQ_LEN` is **8192**, set by the longest record across both corpora",
        "(listening tops out at 6343 tokens; reading at 4558). The data cell",
        "hard-fails if anything would actually be truncated.",
        "",
        "### Why one model instead of one per section",
        "`GENERATOR_MODEL` and `EVALUATOR_MODEL` in `backend/.env` are single",
        "globals, not per-section — so per-section fine-tunes cannot be served",
        "simultaneously without adding section-aware routing to",
        "`app/llm/client.py` AND keeping four q4 GGUFs (~13 GB) resident on a CPU",
        "box. Training one model over the union avoids both costs and keeps the",
        "existing env vars working untouched.",
        "",
        "The tradeoff to keep visible: a multi-task 3B may be weaker per-section",
        "than a specialist, and adding a section later means retraining this shared",
        "model instead of shipping a new one independently. If per-section quality",
        "turns out to matter more than serving cost, use the per-section notebooks",
        "and add the routing.",
    ),
)

for cfg in (LISTENING, READING, COMBINED):
    (HERE / f"{cfg.section}_generator_qlora_kaggle.ipynb").write_text(
        json.dumps(generator_notebook(cfg), indent=1, ensure_ascii=False),
        encoding="utf-8",
    )
    (HERE / f"{cfg.section}_evaluator_qlora_kaggle.ipynb").write_text(
        json.dumps(evaluator_notebook(cfg), indent=1, ensure_ascii=False),
        encoding="utf-8",
    )
    print(
        f"wrote {cfg.section}_generator_qlora_kaggle.ipynb "
        f"({record_count(cfg.gen_files)} records) and "
        f"{cfg.section}_evaluator_qlora_kaggle.ipynb "
        f"({record_count(cfg.eval_files)} records)"
    )

(HERE / "gguf_export_kaggle.ipynb").write_text(
    json.dumps(conversion, indent=1, ensure_ascii=False), encoding="utf-8"
)
print("wrote gguf_export_kaggle.ipynb")
