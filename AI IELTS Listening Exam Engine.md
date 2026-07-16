# **AI IELTS Listening Exam Engine — Complete System Design Prompt**

## **Role**

You are a Senior AI Research Engineer specializing in Large Language Models, Speech AI, Instruction Fine-tuning, Retrieval, Synthetic Data Generation, and Educational Assessment.

Your task is to design and implement a complete AI system capable of generating unlimited IELTS Listening examinations that are indistinguishable from official IELTS Listening tests while remaining completely original.

The generated examinations must not copy Cambridge IELTS content. Instead, the system must learn the hidden design principles behind IELTS Listening exams and generate new tests that follow those principles.

The final product should feel exactly like taking a real IELTS Listening exam.

---

# **Primary Goal**

Create an AI IELTS Listening Engine capable of:

• Generating unlimited listening exams • Matching official IELTS structure • Producing realistic multi-speaker conversations • Generating professional-quality audio • Producing answer keys • Evaluating student answers • Estimating IELTS Listening Band Scores • Giving intelligent feedback

The architecture should be modular internally but appear as one seamless IELTS experience to users.

---

# **Foundation Models**

## **1\. Core Generator Model**

Model:

Qwen2.5-14B-Instruct

Purpose

Generate

• Blueprint • Listening dialogue • Questions • Answer key • Accepted answer variants • Examiner explanation

Fine-tuning

LoRA / QLoRA

Training Type

Supervised Fine-Tuning (SFT)

---

## **2\. Speech Recognition**

Model

Whisper Large-v3

Purpose

• Convert student speech to text • Timestamp audio • High transcription accuracy

---

## **3\. Speech Generation**

Model

An expressive multi-speaker conversational TTS model (for example, Sesame CSM if licensing and deployment fit, or Coqui XTTS v2 for local deployment).

Purpose

Generate natural IELTS-quality conversations with:

• Multiple speakers • British-style accents if desired • Hesitations • Corrections • Interruptions • Pauses • Natural pacing

---

# **Dataset Construction**

Input Sources

• Cambridge IELTS Listening PDFs • Cambridge IELTS audio recordings

Do NOT train directly on PDFs.

Instead, convert every test into structured JSON.

Example

{ section, topic, dialogue, speakers, speaker\_roles, difficulty, question\_types, answers, accepted\_variants, distractors, answer\_positions, speech\_rate, pauses, corrections, audio\_duration, vocabulary\_level, information\_density }

Build this dataset for every Cambridge Listening test.

---

# **Training Objective**

Do NOT teach the model to imitate text.

Teach it to generate exams from design specifications.

Learning Target

Blueprint

↓

Dialogue Plan

↓

Dialogue

↓

Question Generation

↓

Answer Key

↓

Accepted Answers

↓

Evaluation Metadata

---

# **Generator Input Format**

Input

Generate a Listening Test

Section: 3

Difficulty: Medium

Topic: Student Discussion

Question Types:

Multiple Choice

Sentence Completion

Target Duration:

6 minutes

Output

1. Blueprint  
2. Dialogue  
3. Audio Performance Instructions  
4. Questions  
5. Official Answers  
6. Accepted Variants  
7. Evaluation Metadata

---

# **Hidden IELTS Structure**

The model must learn

Section progression

Difficulty progression

Answer ordering

Distractor placement

Corrections

Information density

Speaker interaction

Natural hesitations

Vocabulary progression

Question sequencing

Memory load

Speech pacing

Accent consistency

Topic transitions

The generated exams should statistically resemble official IELTS Listening exams without reproducing copyrighted content.

---

# **Audio Performance Instructions**

Instead of generating only dialogue, generate acting instructions.

Example

Speaker A

Female

British

Friendly

145 WPM

Pause 300 ms

Correct herself once

Speaker B

Male

Professional

Slightly faster

Natural interruptions

The TTS model converts these instructions into realistic speech.

---

# **Evaluation Model**

Use a separate LoRA checkpoint on the same Qwen2.5-14B-Instruct base (or a smaller Qwen2.5-7B-Instruct model if efficiency is preferred).

Training Input

Question

Official Answer

Accepted Variants

Student Answer

Output

Correct / Incorrect

Reason

Correct Answer

Skill Tested

---

# **Automatic Evaluation Pipeline**

Student Audio

↓

Whisper Large-v3

↓

Student Answer

↓

Normalizer

↓

Evaluation Model

↓

40 Question Score

↓

Band Prediction

↓

Feedback Report

---

# **Feedback**

Generate

Overall Score

Band Estimate

Section Scores

Correct Answers

Incorrect Answers

Mistake Analysis

Skill Analysis

Learning Recommendations

Example

Overall

33 / 40

Estimated Band

7.0

Weak Skills

Speaker corrections

Academic vocabulary

Fast conversations

Recommendation

Practice Section 3 discussions.

---

# **System Pipeline**

Cambridge PDFs

Cambridge Audio

↓

Dataset Extraction

↓

Structured JSON Dataset

↓

LoRA Fine-tuning

↓

Qwen2.5-14B Generator

↓

Listening Dialogue

↓

Performance Directions

↓

Conversational TTS

↓

Listening Audio

↓

Question Paper

↓

Student Takes Test

↓

Whisper Large-v3

↓

Evaluation Model

↓

Band Score

↓

Personalized Feedback

---

# **Constraints**

The system must

Never copy Cambridge content.

Generate unique dialogues every time.

Preserve official IELTS timing.

Preserve official question order.

Generate realistic distractors.

Maintain one correct answer per question.

Produce natural conversations.

Follow IELTS Listening difficulty progression.

Output valid JSON for downstream processing when requested.

The final experience should convince users they are taking a genuine IELTS Listening examination while ensuring all generated material is original and derived from learned exam design principles rather than copied content.

