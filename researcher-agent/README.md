# Researcher Agent

An evidence-grounded AI research workspace for finding, importing, analyzing, comparing, and questioning academic papers.

Built for **AI + Cloud + Security research**, but domain-independent.

**Stack:** Python, Flask, SQLite, pdfplumber/pypdf, NumPy, scikit-learn, HTML/CSS/JavaScript.

## Features

- Academic paper search via Semantic Scholar, Crossref, and arXiv
- PDF upload and text extraction
- Section-aware, page-aware chunking
- Local/offline embeddings
- Evidence-grounded paper chat
- Source and page-level evidence tracking
- Paper analysis
- Paper comparison
- Research Gap Finder
- Research Questions
- Experiment Planner
- Literature Review
- Research Projects
- Paper metadata editing
- Safe paper deletion
- Prompt-injection protection
- SSRF and upload security controls
- Retrieval and citation validation
- LLM/API failure handling

## Research Focus

The project is now being used as a research prototype for:

> **Evaluating the reliability of evidence-grounded LLM research assistants.**

The Researcher Agent generates answers from academic papers, while a separate **AI Evidence Analyzer** evaluates whether those answers are actually supported by the provided evidence.

Current failure categories being investigated:

- Retrieval failure
- Unsupported answers
- Citation errors
- Incorrect answers despite relevant evidence
- Inappropriate uncertainty
- PDF/document extraction issues
- Answer instability

## Current Research Collection

Five papers are currently used for evaluation:

1. Efficient Fairness Testing in Large Language Models
2. Metamorphic Testing for Fairness Evaluation in LLMs
3. Meta-Fair: AI-Assisted Fairness Testing of Large Language Models
4. G-Retriever: Retrieval-Augmented Generation for Textual Graph Understanding and Question Answering
5. RoBERTa: A Robustly Optimized BERT Pretraining Approach

Initial evaluation:

**5 papers × 5 standardized questions = 25 cases**

Each answer is evaluated for:

- Correctness
- Evidence support
- Citation accuracy
- Appropriate uncertainty

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py

Open http://localhost:5000.

Tests
pytest -q

Latest verified status:

62 tests passed

Architecture
Academic Papers
      ↓
PDF Extraction
      ↓
Retrieval
      ↓
LLM Answer
      ↓
Evidence + Citation
      ↓
AI Evidence Analyzer
      ↓
Failure Analysis
Limitations
Local single-user application
No OCR for scanned PDFs
Section detection is heuristic
External LLM/API availability affects live evaluation
Current research evaluation uses a limited initial paper/question set
Reliability claims require further empirical evaluation
Research Direction

The implementation phase is largely complete.

The current focus is empirical evaluation, failure-mode analysis, and understanding the limitations of evidence-grounded LLM research assistants.
