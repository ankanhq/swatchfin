"""Reusing a recent guide: the same site, asked for again within 24 hours, isn't read again.

A guide costs TinyFish calls and a language model call, and a website
rarely changes its brand in a day. So when someone asks for a site that
already has a complete guide from the last REUSE_HOURS hours (24 unless
.env says otherwise), they get that guide. It keeps its own date, so it
never claims to be fresher than it is. A failed guide is never reused,
so it can be tried again.

Searches are matched by a "key":
- a web address by its site: "https://www.stripe.com/", "stripe.com" and
  "STRIPE.com/" are all "site:stripe.com";
- a company name by its letters: "Duolingo" and "duolingo" are both
  "name:duolingo".
A finished guide is remembered under its search's key and its website's
key, so "Stripe" after "stripe.com" is reused too: once Search has found
the site (pipeline.py asks JobRun.earlier_guide), the guide stops there.

The list is kept in memory, and rebuilt from the saved guides when the
server starts (jobs.py). On a server whose files are wiped when it
restarts (Render's free plan), it starts empty.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from app.extract.resolve import ParsedQuery


def site_key(url: str) -> str:
    """The key for a website address: its host without "www.", and its path without the last "/".

    "https://www.stripe.com/" -> "site:stripe.com", "https://www.ikea.com/de/" -> "site:ikea.com/de".
    The query string stays (a site may choose its language with it); the #fragment doesn't.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    port = f":{parts.port}" if parts.port else ""
    path = parts.path.rstrip("/")
    query = f"?{parts.query}" if parts.query else ""
    return f"site:{host}{port}{path}{query}"


def query_key(query: ParsedQuery) -> str:
    """The key for a checked search: its site for a web address, its letters for a company name."""
    if query.kind == "url" and query.url:
        return site_key(query.url)
    return f"name:{query.text.casefold()}"


def ago(made_at: datetime, now: datetime | None = None) -> str:
    """How long ago, in words: "a few minutes ago", "1 hour ago", "5 hours ago"."""
    hours = int(((now or datetime.now(UTC)) - made_at).total_seconds() // 3600)
    if hours < 1:
        return "a few minutes ago"
    return f"{hours} hour{'s' if hours != 1 else ''} ago"


class RecentGuides:
    """Which complete guide was made for which key, for the last `hours` hours.

    In plain English: a small address book. remember() writes a guide's ID
    under each of its keys, with the time the site was read. find() looks
    a key up and gives the ID back only while that time is recent enough.
    """

    def __init__(self, hours: float) -> None:
        self.window = timedelta(hours=hours)
        self._guides: dict[str, tuple[str, datetime]] = {}

    def remember(self, keys: set[str], job_id: str, made_at: datetime) -> None:
        if not self.window:
            return
        now = datetime.now(UTC)
        for key in keys:
            current = self._guides.get(key)
            # Two guides for one key: keep the newer.
            if current is None or current[1] <= made_at:
                self._guides[key] = (job_id, made_at)
        # Forget what is too old to be reused, so the book never grows past a day of guides.
        for key, (_job_id, made) in list(self._guides.items()):
            if now - made >= self.window:
                del self._guides[key]

    def find(self, key: str) -> str | None:
        """The ID of a guide made for this key recently enough, or None."""
        entry = self._guides.get(key)
        if entry is None:
            return None
        job_id, made_at = entry
        if datetime.now(UTC) - made_at >= self.window:
            del self._guides[key]
            return None
        return job_id

    def forget(self, key: str) -> None:
        self._guides.pop(key, None)
