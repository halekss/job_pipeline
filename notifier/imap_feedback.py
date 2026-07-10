"""
imap_feedback.py - Lecture des réponses "pas intéressé" par IMAP (COM-13)

Lit les mails non lus dont le sujet contient le marqueur
[Job Pipeline Feedback], envoyés en réponse au lien mailto généré par
notifier/formatter.py. Réutilise les identifiants SMTP (Gmail accepte les
mots de passe d'application aussi bien en IMAP qu'en SMTP) — aucun nouveau
secret requis. Cf. docs/superpowers/specs/2026-07-10-feedback-loop-design.md.
"""

import imaplib
import email
import logging
import os
import re
from dataclasses import dataclass
from email.header import decode_header
from typing import Optional

logger = logging.getLogger(__name__)

SUBJECT_MARKER = "[Job Pipeline Feedback]"
OFFER_ID_RE = re.compile(r"\[Job Pipeline Feedback\]\s*(\S+)")
REASON_RE = re.compile(r"raison\s*(?:\(optionnel\))?\s*:\s*(.+)", re.IGNORECASE)


@dataclass
class FeedbackEmail:
    offer_id: str
    reason: Optional[str]


def _decode_subject(raw_subject: str) -> str:
    """Décode un sujet potentiellement encodé (RFC 2047) en str lisible."""
    if not raw_subject:
        return ""
    decoded = ""
    for text, charset in decode_header(raw_subject):
        if isinstance(text, bytes):
            decoded += text.decode(charset or "utf-8", errors="replace")
        else:
            decoded += text
    return decoded


def _extract_text_body(msg: email.message.Message) -> str:
    """Extrait la partie text/plain d'un email (simple ou multipart)."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
        return ""

    payload = msg.get_payload(decode=True)
    if payload is None:
        return ""
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _parse_reason(body: str) -> Optional[str]:
    """Extrait la raison de la ligne 'Raison (optionnel) : ...' si remplie."""
    match = REASON_RE.search(body)
    if not match:
        return None
    reason = match.group(1).strip()
    return reason or None


def fetch_feedback_emails(
    host: str = None,
    port: int = 993,
    user: str = None,
    password: str = None,
) -> list[FeedbackEmail]:
    """
    Se connecte en IMAP et retourne les feedbacks non lus trouvés.

    Ne lève jamais d'exception : toute erreur (credentials manquants,
    connexion, IMAP) est loguée et retourne une liste vide, pour ne
    jamais bloquer le run principal.
    """
    host = host or os.getenv("IMAP_HOST", "imap.gmail.com")
    user = user or os.getenv("SMTP_USER")
    password = password or os.getenv("SMTP_PASSWORD")

    if not user or not password:
        logger.error("[Feedback] SMTP_USER/SMTP_PASSWORD requis pour lire les feedbacks IMAP.")
        return []

    results: list[FeedbackEmail] = []

    try:
        imap = imaplib.IMAP4_SSL(host, port)
    except Exception as e:
        logger.error("[Feedback] Erreur de connexion IMAP : %s", e)
        return []

    try:
        imap.login(user, password)
        imap.select("INBOX")

        typ, data = imap.search(None, "UNSEEN", "SUBJECT", f'"{SUBJECT_MARKER}"')
        if typ != "OK":
            logger.warning("[Feedback] Recherche IMAP échouée : %s", typ)
            return []

        message_numbers = data[0].split() if data and data[0] else []

        for num in message_numbers:
            typ, msg_data = imap.fetch(num, "(BODY[])")
            if typ != "OK" or not msg_data or msg_data[0] is None:
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            subject = _decode_subject(msg.get("Subject", ""))

            match = OFFER_ID_RE.search(subject)
            if not match:
                logger.warning("[Feedback] Sujet sans offer_id reconnaissable : %s", subject)
                imap.store(num, "+FLAGS", "\\Seen")
                continue

            offer_id = match.group(1)
            body = _extract_text_body(msg)
            reason = _parse_reason(body)

            results.append(FeedbackEmail(offer_id=offer_id, reason=reason))
            imap.store(num, "+FLAGS", "\\Seen")

    except Exception as e:
        logger.error("[Feedback] Erreur IMAP : %s", e)
        return []
    finally:
        try:
            imap.logout()
        except Exception:
            pass

    return results
