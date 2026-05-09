"""
mailer.py
---------
Responsibility: Format ranked articles into a beautiful HTML email and send it.

Uses Gmail SMTP with App Password (no OAuth complexity).
Credentials loaded from environment variables — never hardcoded.

Setup (one-time):
  1. Gmail → Settings → Security → 2FA on → App Passwords → generate one
  2. Set env vars:
       DIGEST_EMAIL_FROM=you@gmail.com
       DIGEST_EMAIL_TO=you@gmail.com       # can be same or different
       DIGEST_APP_PASSWORD=xxxx xxxx xxxx xxxx

Why smtplib over Gmail API?
  smtplib needs zero OAuth setup. For a personal daily script, it's the
  right tool. Gmail API is better if you're sending to multiple users.
"""

import os
import smtplib
import logging
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

# ── Category colors for the email ─────────────────────────────────────────────
CATEGORY_STYLES: dict[str, dict] = {
    "AI/LLM":        {"bg": "#EDE9FE", "text": "#5B21B6", "border": "#7C3AED"},
    "System Design": {"bg": "#DBEAFE", "text": "#1E40AF", "border": "#3B82F6"},
    "MLOps":         {"bg": "#D1FAE5", "text": "#065F46", "border": "#10B981"},
    "Backend":       {"bg": "#FEF3C7", "text": "#92400E", "border": "#F59E0B"},
    "General Tech":  {"bg": "#F3F4F6", "text": "#374151", "border": "#9CA3AF"},
}

SCORE_EMOJI = {range(9, 11): "🔥", range(7, 9): "⚡", range(5, 7): "📘", range(1, 5): "📎"}

def _score_emoji(score: int) -> str:
    for r, emoji in SCORE_EMOJI.items():
        if score in r:
            return emoji
    return "📎"


# ── HTML builder ───────────────────────────────────────────────────────────────

def _build_article_card(article: dict) -> str:
    style = CATEGORY_STYLES.get(article.get("category", "General Tech"), CATEGORY_STYLES["General Tech"])
    emoji = _score_emoji(article.get("score", 5))
    ranked_by = article.get("ranked_by", "heuristic")
    ranked_label = "🤖 AI ranked" if ranked_by == "llm" else "⚙️ heuristic"

    return f"""
    <div style="margin-bottom:16px;padding:16px 20px;background:#ffffff;
                border:1px solid #E5E7EB;border-left:4px solid {style['border']};
                border-radius:8px;font-family:system-ui,sans-serif;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <span style="font-size:11px;font-weight:600;letter-spacing:0.05em;
                     background:{style['bg']};color:{style['text']};
                     padding:3px 10px;border-radius:999px;">
          {article.get('category','General Tech').upper()}
        </span>
        <span style="font-size:11px;color:#9CA3AF;">{ranked_label}</span>
      </div>

      <a href="{article['url']}" style="font-size:15px;font-weight:600;
               color:#111827;text-decoration:none;line-height:1.4;display:block;margin-bottom:6px;">
        {emoji} {article['title']}
      </a>

      <p style="font-size:13px;color:#6B7280;margin:0 0 10px;line-height:1.5;">
        {article.get('summary','')[:250]}{'…' if len(article.get('summary','')) > 250 else ''}
      </p>

      <div style="display:flex;justify-content:space-between;align-items:center;">
        <span style="font-size:12px;color:#9CA3AF;">
          📰 {article['source']} &nbsp;·&nbsp; 🗓 {article['published'][:10]}
        </span>
        <span style="font-size:12px;font-weight:700;color:{style['border']};">
          Score: {article.get('score', '?')}/10
        </span>
      </div>
    </div>"""


def _group_by_category(articles: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list] = {}
    for a in articles:
        cat = a.get("category", "General Tech")
        groups.setdefault(cat, []).append(a)
    return groups


def build_html(articles: list[dict], stats: dict) -> str:
    """Build the full HTML email body."""
    today = datetime.now().strftime("%A, %d %B %Y")
    groups = _group_by_category(articles)

    # Category sections
    sections_html = ""
    cat_order = ["AI/LLM", "System Design", "MLOps", "Backend", "General Tech"]
    for cat in cat_order:
        if cat not in groups:
            continue
        style = CATEGORY_STYLES.get(cat, CATEGORY_STYLES["General Tech"])
        cards = "".join(_build_article_card(a) for a in groups[cat])
        sections_html += f"""
        <div style="margin-bottom:28px;">
          <h2 style="font-size:13px;font-weight:700;letter-spacing:0.08em;
                     color:{style['text']};margin:0 0 12px;text-transform:uppercase;">
            {cat} ({len(groups[cat])})
          </h2>
          {cards}
        </div>"""

    # Stats bar
    stats_html = f"""
    <div style="background:#F9FAFB;border:1px solid #E5E7EB;border-radius:8px;
                padding:14px 20px;margin-top:24px;font-size:12px;color:#6B7280;
                display:flex;gap:24px;flex-wrap:wrap;">
      <span>📦 Total fetched: <b>{stats.get('total_fetched', '?')}</b></span>
      <span>✅ New articles: <b>{stats.get('total_new', '?')}</b></span>
      <span>🧠 LLM ranked: <b>{stats.get('llm_ranked', '?')}</b></span>
      <span>📚 Total tracked: <b>{stats.get('total_seen', '?')}</b></span>
    </div>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#F3F4F6;font-family:system-ui,sans-serif;">
  <div style="max-width:640px;margin:24px auto;padding:0 16px;">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#1E1B4B 0%,#312E81 100%);
                border-radius:12px;padding:28px 32px;margin-bottom:20px;">
      <div style="font-size:11px;font-weight:600;letter-spacing:0.1em;
                  color:#A5B4FC;margin-bottom:8px;">DAILY TECH DIGEST</div>
      <div style="font-size:24px;font-weight:700;color:#ffffff;margin-bottom:4px;">
        {len(articles)} Articles for You
      </div>
      <div style="font-size:13px;color:#C7D2FE;">{today}</div>
    </div>

    <!-- Articles by category -->
    {sections_html}

    <!-- Stats -->
    {stats_html}

    <!-- Footer -->
    <div style="text-align:center;padding:20px;font-size:11px;color:#9CA3AF;">
      Built with feedparser · Ollama · SQLite · GitHub Actions<br>
      <a href="#" style="color:#6366F1;text-decoration:none;">Unsubscribe</a>
    </div>

  </div>
</body></html>"""


# ── Sender ─────────────────────────────────────────────────────────────────────

def send_email(articles: list[dict], stats: dict) -> bool:
    """
    Send the digest email via Gmail SMTP.

    Returns True on success, False on failure.
    Reads credentials from environment — never from code.
    """
    sender = os.environ.get("DIGEST_EMAIL_FROM", "").strip()

    recipients_raw = os.environ.get("DIGEST_EMAIL_TO", "").strip()

    recipients = [
        email.strip()
        for email in recipients_raw.split(",")
        if email.strip()
    ]

    app_password = os.environ.get("DIGEST_APP_PASSWORD", "").strip()

    if not all([sender, recipients, app_password]):
        logger.warning(
            "Mailer: credentials not set. Export DIGEST_EMAIL_FROM, "
            "DIGEST_EMAIL_TO, DIGEST_APP_PASSWORD to send real email."
        )
        logger.info("Mailer: printing email preview to console instead")
        _preview_console(articles)
        return False

    today = datetime.now().strftime("%d %b %Y")
    subject = f"🧠 Dev Digest — {len(articles)} articles · {today}"

    # ── Build email ─────────────────────────────────────────────
    msg = MIMEMultipart("alternative")

    msg["Subject"] = subject
    msg["From"] = f"Dev Digest <{sender}>"

    # visible recipient
    msg["To"] = sender

    # hidden recipients
    msg["Bcc"] = ", ".join(recipients)

    html_body = build_html(articles, stats)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # ── Send via Gmail SMTP ────────────────────────────────────
    try:
        logger.info("Mailer: connecting to smtp.gmail.com:587")

        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
            server.ehlo()

            # secure TLS connection
            server.starttls()

            # login using Gmail app password
            server.login(sender, app_password)

            # send email
            server.sendmail(
                sender,
                recipients,
                msg.as_string()
            )

        logger.info(
            f"Mailer: ✅ email sent to {len(recipients)} recipients | subject='{subject}'"
        )

        return True

    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Mailer: authentication failed — check DIGEST_APP_PASSWORD"
        )

    except smtplib.SMTPException as e:
        logger.error(f"Mailer: SMTP error — {e}")

    except Exception as e:
        logger.error(f"Mailer: unexpected error — {e}")

    return False


def _preview_console(articles: list[dict]) -> None:
    """Print a plain-text preview when email creds are not set."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="📬 Email Preview (would be sent)", show_lines=True)
    table.add_column("Score", style="bold cyan", width=6)
    table.add_column("Category", style="magenta", width=14)
    table.add_column("Source", style="yellow", width=22)
    table.add_column("Title", style="white")

    for a in articles:
        table.add_row(
            str(a.get("score", "?")),
            a.get("category", "-"),
            a.get("source", "-"),
            a["title"][:80],
        )
    console.print(table)
