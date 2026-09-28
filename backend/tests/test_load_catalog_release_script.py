import io
import tarfile

import httpx
import pytest
import respx

from app.services.catalog_loader import CatalogLoadError
from scripts.load_catalog_release import resolve_release

URL = "https://github.com/devkevintoledo-tech/margin/releases/download/catalog-2026.10.1/catalog-2026.10.1.tar.gz"


def tarball(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_a_folder_is_used_as_is(tmp_path):
    assert resolve_release(str(tmp_path), tmp_path / "releases") == tmp_path


@respx.mock
def test_a_tag_is_downloaded_and_unpacked(tmp_path):
    respx.get(URL).mock(return_value=httpx.Response(200, content=tarball({"catalog-2026.10.1/manifest.json": b"{}"})))
    with httpx.Client() as client:
        folder = resolve_release("catalog-2026.10.1", tmp_path, client)
    assert (folder / "manifest.json").read_bytes() == b"{}"


def test_an_already_downloaded_tag_is_not_fetched_again(tmp_path):
    (tmp_path / "catalog-2026.10.1").mkdir()
    assert resolve_release("2026.10.1", tmp_path).name == "catalog-2026.10.1"


@respx.mock
def test_a_tarball_escaping_its_folder_is_refused(tmp_path):
    respx.get(URL).mock(return_value=httpx.Response(200, content=tarball({"../evil": b"x"})))
    with httpx.Client() as client, pytest.raises(tarfile.TarError):
        resolve_release("catalog-2026.10.1", tmp_path / "releases", client)
    assert not (tmp_path / "evil").exists()


@respx.mock
def test_a_missing_release_is_a_clean_refusal(tmp_path):
    respx.get(URL).mock(return_value=httpx.Response(404))
    with httpx.Client() as client, pytest.raises(CatalogLoadError, match="could not download"):
        resolve_release("catalog-2026.10.1", tmp_path, client)


def test_nonsense_is_refused(tmp_path):
    with pytest.raises(CatalogLoadError):
        resolve_release("latest", tmp_path)
