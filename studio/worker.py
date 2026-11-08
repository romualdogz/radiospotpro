"""Render-Warteschlange: holt Aufträge aus der Datenbank und rendert jeden in einem eigenen Prozess.

Produktion (eigener Dienst, z. B. systemd):   python -m studio.worker
Am Mac / lokal läuft derselbe Code als Thread im Webserver (STUDIO_WORKER=inline).
Grenzen: STUDIO_RENDER_WORKERS parallele Jobs, STUDIO_RENDER_TIMEOUT Sekunden je Job.
"""
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import update

from .config import settings
from .database import SessionLocal, init_db
from .models import Export, aware, now

log = logging.getLogger("studio.worker")
ROOT = Path(__file__).resolve().parent.parent


def claim_next() -> int | None:
    """Ältesten wartenden Auftrag atomar auf „running“ setzen (sicher bei mehreren Workern)."""
    with SessionLocal() as db:
        for (job_id,) in db.query(Export.id).filter(Export.status == "queued").order_by(Export.id).limit(5):
            res = db.execute(update(Export).where(Export.id == job_id, Export.status == "queued")
                             .values(status="running", started_at=now()))
            db.commit()
            if res.rowcount == 1:
                return job_id
    return None


def _fail(job_id: int, message: str) -> None:
    with SessionLocal() as db:
        job = db.get(Export, job_id)
        if job and job.status == "running":
            job.status, job.error, job.finished_at = "failed", message, now()
            db.commit()


def process(job_id: int) -> None:
    """Auftrag in eigenem Prozess rendern; bei Zeitüberschreitung wird der Prozess beendet."""
    try:
        subprocess.run([sys.executable, "-m", "studio.render", str(job_id)], cwd=ROOT, env=os.environ.copy(),
                       timeout=settings.render_timeout_s, check=False)
    except subprocess.TimeoutExpired:
        log.warning("Export %s: Zeitlimit überschritten", job_id)
        _fail(job_id, f"Abgebrochen: Rendern dauerte länger als {settings.render_timeout_s} Sekunden.")
        return
    _fail(job_id, "Rendern fehlgeschlagen.")  # nur wirksam, falls der Prozess abgestürzt ist


def recover_stale() -> None:
    """Nach einem Neustart hängengebliebene Aufträge als fehlgeschlagen markieren."""
    cutoff = now() - timedelta(seconds=settings.render_timeout_s + 60)
    with SessionLocal() as db:
        for job in db.query(Export).filter(Export.status == "running"):
            if job.started_at is None or aware(job.started_at) < cutoff:
                job.status, job.error, job.finished_at = "failed", "Abgebrochen (Neustart).", now()
        db.commit()


def cleanup() -> int:
    """Exporte nach STUDIO_EXPORT_DAYS Tagen löschen (Datei weg, Eintrag bleibt für die Exportzählung)."""
    from .storage import delete_export_file
    cutoff = now() - timedelta(days=settings.export_days)
    count = 0
    with SessionLocal() as db:
        for job in db.query(Export).filter(Export.status == "done"):
            if aware(job.finished_at or job.created_at) < cutoff:
                delete_export_file(job)
                job.status, job.size_bytes = "expired", 0
                count += 1
        db.commit()
    return count


def loop(stop: threading.Event, poll: float = 1.0) -> None:
    last_cleanup = 0.0
    while not stop.is_set():
        try:
            if time.monotonic() - last_cleanup > 3600:
                cleanup()
                last_cleanup = time.monotonic()
            job_id = claim_next()
            if job_id is not None:
                process(job_id)
                continue
        except Exception:  # noqa: BLE001 – Worker darf nicht sterben
            log.exception("Worker-Fehler")
        stop.wait(poll)


def start_threads(stop: threading.Event) -> list[threading.Thread]:
    recover_stale()
    threads = [threading.Thread(target=loop, args=(stop,), name=f"studio-render-{i}", daemon=True)
               for i in range(max(1, settings.render_workers))]
    for t in threads:
        t.start()
    return threads


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    init_db()
    stop = threading.Event()
    threads = start_threads(stop)
    log.info("Studio-Worker läuft (%d parallel, Zeitlimit %d s)", len(threads), settings.render_timeout_s)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
