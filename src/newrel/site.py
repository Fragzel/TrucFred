"""Assemblage du site statique (site/ + releases.json) et serveur local de prévisualisation."""

from __future__ import annotations

import contextlib
import functools
import http.server
import shutil
from pathlib import Path
from typing import ClassVar

EXCLUDED = ("sample.json",)


def build(site_dir: Path, out_dir: Path, releases_json: str) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(site_dir, out_dir, ignore=shutil.ignore_patterns(*EXCLUDED))
    (out_dir / "releases.json").write_text(releases_json, encoding="utf-8")


class _Handler(http.server.SimpleHTTPRequestHandler):
    # Sous Windows, le registre peut associer .js à text/plain : les modules ES refusent alors
    # de se charger. On fixe les types utiles.
    extensions_map: ClassVar[dict[str, str]] = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".json": "application/json",
        ".css": "text/css",
        ".svg": "image/svg+xml",
    }


def serve(out_dir: Path, port: int) -> None:
    handler = functools.partial(_Handler, directory=str(out_dir))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
        print(f"Site servi sur http://127.0.0.1:{port}/ (Ctrl+C pour arrêter)")
        with contextlib.suppress(KeyboardInterrupt):
            server.serve_forever()
