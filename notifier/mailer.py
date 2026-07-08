"""
email.py - Envoi des alertes mail via smtplib

Compatible Gmail (mot de passe d'application) et tout SMTP standard.

Variables d'env requises :
    SMTP_HOST       (défaut : smtp.gmail.com)
    SMTP_PORT       (défaut : 587)
    SMTP_USER       ton adresse email
    SMTP_PASSWORD   mot de passe d'application Gmail
    ALERT_RECIPIENT destinataire (peut être le même que SMTP_USER)
"""

import os
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

try:
    from sources.base_source import JobOffer
except ImportError:
    import sys, os as _os
    sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), ".."))
    from sources.base_source import JobOffer

from notifier.formatter import render_email  # noqa

logger = logging.getLogger(__name__)


class EmailNotifier:
    """
    Envoie un email HTML récapitulatif des nouvelles offres.

    Usage :
        notifier = EmailNotifier()
        notifier.send(offers, keywords=["Data Analyst"], locations=["59"])
    """

    def __init__(
        self,
        smtp_host: str = None,
        smtp_port: int = None,
        smtp_user: str = None,
        smtp_password: str = None,
        recipient: str = None,
    ):
        self.smtp_host = smtp_host or os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(smtp_port or os.getenv("SMTP_PORT", 587))
        self.smtp_user = smtp_user or os.getenv("SMTP_USER")
        self.smtp_password = smtp_password or os.getenv("SMTP_PASSWORD")
        self.recipient = recipient or os.getenv("ALERT_RECIPIENT") or self.smtp_user

        if not self.smtp_user or not self.smtp_password:
            raise ValueError(
                "SMTP_USER et SMTP_PASSWORD sont requis. "
                "Pour Gmail, crée un mot de passe d'application sur "
                "https://myaccount.google.com/apppasswords"
            )

    def send(
        self,
        offers: list[JobOffer],
        keywords: list[str],
        locations: list[str],
    ) -> bool:
        """
        Génère et envoie l'email d'alerte.

        Args:
            offers    : offres à inclure dans l'email
            keywords  : mots-clés de recherche (pour l'affichage)
            locations : localisations (pour l'affichage)

        Returns:
            True si l'envoi a réussi, False sinon.
        """
        if not offers:
            logger.info("Aucune nouvelle offre, email non envoyé.")
            return False

        subject = self._build_subject(offers)
        html_body = render_email(offers, keywords, locations)
        msg = self._build_message(subject, html_body)

        return self._send_message(msg)

    def send_empty_digest(self, keywords: list[str], locations: list[str]) -> bool:
        """Envoie un email même s'il n'y a pas de nouvelles offres (optionnel)."""
        subject = f"[Job Pipeline] Aucune nouvelle offre · {datetime.now().strftime('%d/%m/%Y')}"
        html_body = render_email([], keywords, locations)
        msg = self._build_message(subject, html_body)
        return self._send_message(msg)

    # ------------------------------------------------------------------
    # Helpers privés
    # ------------------------------------------------------------------

    def _build_subject(self, offers: list[JobOffer]) -> str:
        date_str = datetime.now().strftime("%d/%m/%Y")
        nb = len(offers)
        # Compte les alternances
        alt = sum(
            1 for o in offers
            if any(m in (o.contract_type or "").lower() or m in o.title.lower()
                   for m in ["alternance", "apprenti"])
        )
        if alt > 0:
            return f"[Job Pipeline] {nb} offre(s) · {alt} alternance(s) · {date_str}"
        return f"[Job Pipeline] {nb} nouvelle(s) offre(s) · {date_str}"

    def _build_message(self, subject: str, html_body: str) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.smtp_user
        msg["To"] = self.recipient
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        return msg

    def _send_message(self, msg: MIMEMultipart) -> bool:
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.smtp_user, self.recipient, msg.as_string())

            logger.info(
                "Email envoyé à %s (sujet : %s)", self.recipient, msg["Subject"]
            )
            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error(
                "Échec d'authentification SMTP. Détail : %s", str(e)
            )
            return False
        except smtplib.SMTPException as e:
            logger.error("Erreur SMTP : %s", e)
            return False
        except OSError as e:
            logger.error("Erreur réseau : %s", e)
            return False