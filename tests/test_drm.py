"""Tests for the ADEPT (ACS4) fulfilment toolchain wrapper."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ebiblio_mcp import drm
from ebiblio_mcp.drm import AdeptToolchain, DrmError, convert_ebook


class FakeRun:
    """Records subprocess invocations and fabricates their outputs."""

    def __init__(self, behaviours: dict[str, object] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.behaviours = behaviours or {}

    def __call__(self, cmd, capture_output=True, text=True, timeout=None):  # noqa: ANN001
        self.calls.append(list(cmd))
        binary = Path(cmd[0]).name
        behaviour = self.behaviours.get(binary)
        if callable(behaviour):
            behaviour(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")


@pytest.fixture()
def workdir(tmp_path: Path) -> Path:
    return tmp_path


def activate(cmd: list[str]) -> None:
    out = Path(cmd[cmd.index("--output-dir") + 1])
    out.mkdir(parents=True, exist_ok=True)
    (out / "device.xml").write_text("<device/>", encoding="utf-8")
    (out / "activation.xml").write_text("<activation/>", encoding="utf-8")


def test_ensure_activated_creates_anonymous_device(monkeypatch, workdir: Path) -> None:
    run = FakeRun({"adept_activate": activate})
    monkeypatch.setattr(drm.subprocess, "run", run)
    monkeypatch.setattr(drm.shutil, "which", lambda name: f"/usr/local/bin/{name}")

    toolchain = AdeptToolchain(workdir / "adept")
    toolchain.ensure_activated()

    assert toolchain.activated
    assert run.calls[0][0].endswith("adept_activate")
    assert "--anonymous" in run.calls[0]
    assert "--random-serial" in run.calls[0]
    assert (workdir / "adept").stat().st_mode & 0o777 == 0o700


def test_ensure_activated_is_idempotent(monkeypatch, workdir: Path) -> None:
    run = FakeRun({"adept_activate": activate})
    monkeypatch.setattr(drm.subprocess, "run", run)
    monkeypatch.setattr(drm.shutil, "which", lambda name: f"/usr/local/bin/{name}")

    toolchain = AdeptToolchain(workdir / "adept")
    toolchain.ensure_activated()
    toolchain.ensure_activated()
    assert len(run.calls) == 1


def test_ensure_activated_reports_failure(monkeypatch, workdir: Path) -> None:
    def boom(cmd, capture_output=True, text=True, timeout=None):  # noqa: ANN001
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="activation refused")

    monkeypatch.setattr(drm.subprocess, "run", boom)
    monkeypatch.setattr(drm.shutil, "which", lambda name: f"/usr/local/bin/{name}")

    with pytest.raises(DrmError) as excinfo:
        AdeptToolchain(workdir / "adept").ensure_activated()
    assert "activation refused" in str(excinfo.value)


def test_fulfil_acsm_downloads_and_removes_drm(monkeypatch, workdir: Path) -> None:
    def download(cmd: list[str]) -> None:
        Path(cmd[cmd.index("--output-file") + 1]).write_bytes(b"encrypted")

    def remove(cmd: list[str]) -> None:
        Path(cmd[cmd.index("--output-file") + 1]).write_bytes(b"plain epub")

    run = FakeRun({"adept_activate": activate, "acsmdownloader": download, "adept_remove": remove})
    monkeypatch.setattr(drm.subprocess, "run", run)
    monkeypatch.setattr(drm.shutil, "which", lambda name: f"/usr/local/bin/{name}")

    acsm = workdir / "book.acsm"
    acsm.write_text("<fulfillmentToken/>", encoding="utf-8")
    toolchain = AdeptToolchain(workdir / "adept")
    result = toolchain.fulfil_acsm(acsm, workdir / "out")

    assert result.read_bytes() == b"plain epub"
    assert result.name == "book.drm-free.epub"
    binaries = [Path(call[0]).name for call in run.calls]
    assert binaries == ["adept_activate", "acsmdownloader", "adept_remove"]
    assert "--adept-directory" in run.calls[1]


def test_fulfil_acsm_failure(monkeypatch, workdir: Path) -> None:
    def download_fail(cmd, capture_output=True, text=True, timeout=None):  # noqa: ANN001
        if Path(cmd[0]).name == "acsmdownloader":
            return subprocess.CompletedProcess(cmd, 3, stdout="", stderr="E_ADEPT_REQUEST_EXPIRED")
        activate(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(drm.subprocess, "run", download_fail)
    monkeypatch.setattr(drm.shutil, "which", lambda name: f"/usr/local/bin/{name}")
    acsm = workdir / "book.acsm"
    acsm.write_text("<fulfillmentToken/>", encoding="utf-8")
    with pytest.raises(DrmError) as excinfo:
        AdeptToolchain(workdir / "adept").fulfil_acsm(acsm, workdir / "out")
    assert "E_ADEPT_REQUEST_EXPIRED" in str(excinfo.value)


def test_missing_binary_is_reported(monkeypatch, workdir: Path) -> None:
    monkeypatch.setattr(drm.shutil, "which", lambda name: None)
    with pytest.raises(DrmError) as excinfo:
        AdeptToolchain(workdir / "adept").ensure_activated()
    assert "libgourou" in str(excinfo.value)


def test_convert_ebook_uses_calibre(monkeypatch, workdir: Path) -> None:
    run = FakeRun()
    monkeypatch.setattr(drm.subprocess, "run", run)
    source = workdir / "book.epub"
    source.write_bytes(b"epub")

    def fake_run(cmd, capture_output=True, text=True, timeout=None):  # noqa: ANN001
        Path(cmd[2]).write_bytes(b"mobi")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(drm.subprocess, "run", fake_run)
    out = convert_ebook(source, "mobi", workdir / "book.mobi", ebook_convert="/usr/bin/ebook-convert")
    assert out.read_bytes() == b"mobi"


def test_convert_ebook_without_calibre(monkeypatch, workdir: Path) -> None:
    monkeypatch.setattr(drm.shutil, "which", lambda name: None)
    with pytest.raises(DrmError) as excinfo:
        convert_ebook(workdir / "book.epub", "mobi", workdir / "book.mobi")
    assert "Calibre" in str(excinfo.value)
