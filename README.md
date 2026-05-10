# AI Dev Digest Pipeline

An automated AI-powered newsletter pipeline that fetches engineering and AI blogs from RSS feeds, ranks them using LLMs, stores article history in PostgreSQL, and delivers curated email digests twice daily.

---

# Features

* Fetches articles from AI + engineering RSS feeds
* Deduplicates previously seen articles
* Uses Groq LLM for intelligent ranking
* PostgreSQL-backed persistent storage
* Automated email digest delivery
* GitHub Actions scheduled automation
* Topic-aware filtering and scoring
* Cloud-native architecture

---

# Architecture

```text
GitHub Actions Scheduler
          ↓
      RSS Feed Sources
          ↓
      Fetcher Service
          ↓
   PostgreSQL Deduplicator
          ↓
 Heuristic Shortlister
          ↓
     Groq LLM Ranker
          ↓
   HTML Email Builder
          ↓
      SMTP Mailer
          ↓
      Email Recipients
```

---

# Tech Stack

| Component         | Technology      |
| ----------------- | --------------- |
| Language          | Python          |
| RSS Parsing       | feedparser      |
| LLM Ranking       | Groq API        |
| Database          | Neon PostgreSQL |
| Email Delivery    | SMTP (Gmail)    |
| Scheduling        | GitHub Actions  |
| Config Management | python-dotenv   |
| CLI Logging       | rich            |

---

# Project Structure

```text
blog_fetcher/
│
├── .github/
│   └── workflows/
│       └── digest.yml
│
├── modules/
│   ├── fetcher.py
│   ├── deduplicator.py
│   ├── ranker.py
│   ├── mailer.py
│   ├── shortlister.py
│   └── filters.py
│
├── feeds.py
├── main.py
├── requirements.txt
├── .env
├── .gitignore
└── README.md
```

---

# Setup

## Clone Repository

```bash
git clone <repo-url>
cd blog_fetcher
```

---

## Create Virtual Environment

```bash
python -m venv venv
source venv/bin/activate
```

Windows:

```bash
venv\Scripts\activate
```

---

## Install Dependencies

```bash
pip install -r requirements.txt
```

---

# Environment Variables

Create:

```text
.env
```

Example:

```ini
# Email
DIGEST_EMAIL_FROM=yourgmail@gmail.com
DIGEST_EMAIL_TO=friend1@gmail.com,friend2@gmail.com
DIGEST_APP_PASSWORD=your_app_password

# Groq
GROQ_API_KEY=your_groq_key
MODEL_NAME=llama-3.1-8b-instant

# PostgreSQL
DATABASE_URL=postgresql://user:password@host/dbname?sslmode=require
```

---

# PostgreSQL Setup

Recommended:

* Neon PostgreSQL

The application automatically creates required tables on first run.

---

# Running Locally

```bash
python main.py --days 7 --top 12
```

---

# Dry Run (No Email)

```bash
python main.py --days 7 --top 12 --dry-run
```

---

# GitHub Actions Automation

The pipeline is automatically scheduled using GitHub Actions.

Workflow file:

```text
.github/workflows/digest.yml
```

Current schedule:

```yaml
0 3,15 * * *
```

Runs twice daily:

* 8:30 AM IST
* 8:30 PM IST

---

# GitHub Secrets

Add these repository secrets:

| Secret              | Purpose               |
| ------------------- | --------------------- |
| DIGEST_EMAIL_FROM   | Sender email          |
| DIGEST_EMAIL_TO     | Recipient emails      |
| DIGEST_APP_PASSWORD | Gmail app password    |
| GROQ_API_KEY        | Groq API access       |
| DATABASE_URL        | PostgreSQL connection |

---

# Ranking Pipeline

The ranking system combines:

## 1. Heuristic Filtering

Keyword + source based relevance scoring.

Topics include:

* AI/LLM
* Agents
* RAG
* MLOps
* System Design
* Backend Engineering
* Infrastructure

---

## 2. LLM Ranking

Groq-hosted LLM evaluates:

* relevance
* technical depth
* usefulness
* novelty

Outputs:

* score
* category
* AI summary

---

# Stored Metadata

Each processed article stores:

* URL
* Title
* Source
* Published timestamp
* AI score
* Category
* Summary
* Seen timestamp

---

# Email Digest

The pipeline generates an HTML digest including:

* ranked articles
* summaries
* source attribution
* categories
* timestamps

Delivered using Gmail SMTP.

---

# Future Improvements

* User subscriptions
* Category preferences
* Semantic search / RAG
* Embedding storage
* Dashboard UI
* Slack/Discord integration
* Trending analytics
* Multi-user support

---

# Key Concepts Demonstrated

This project demonstrates:

* ETL Pipelines
* RSS ingestion
* AI ranking systems
* PostgreSQL persistence
* Cloud automation
* GitHub Actions orchestration
* Email systems
* Secrets management
* Prompt engineering
* Backend architecture

---

# License

MIT License
