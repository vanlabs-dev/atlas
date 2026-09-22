"""Evidence packets fail closed: release labels are not provenance."""
import importlib.util
from pathlib import Path
import hashlib
import json
import subprocess
import pytest


def evidence():
    spec = importlib.util.spec_from_file_location(
        "evidence", Path(__file__).parents[1] / "evidence.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pin(code=b"\x00asm\x01\x00\x00\x00", spec=467):
    return {"genesis_hash": "0x" + "11" * 32,
            "block_hash": "0x" + "22" * 32, "block_number": 100,
            "runtime_version": {"specVersion": spec},
            "code": "0x" + code.hex(),
            "code_hash": "0x" + hashlib.blake2b(code, digest_size=32).hexdigest(),
            "metadata": "0x6d6574610e00"}


def release(code=b"\x00asm\x01\x00\x00\x00", commit="a" * 40):
    sha = "0x" + hashlib.sha256(code).hexdigest()
    return {"wasm": code, "manifest": {"commit": commit, "wasm_sha256": sha,
            "spec_version": 467}, "digest": {"commit": commit, "sha256": sha},
            "tag_commit": commit, "url": "https://github.com/RaoFoundation/subtensor/releases/tag/v467"}


def official_download(monkeypatch, module, commit, spec=467, code=b"\x00asm\x01\x00\x00\x00"):
    """Mock network bytes only; exercise actual receipt/digest validation."""
    base = "https://api.github.com/repos/RaoFoundation/subtensor/releases/"
    manifest = release(code, commit)["manifest"]
    manifest.update(spec_version=spec, repo="RaoFoundation/subtensor", tag=f"v{spec}", network="finney")
    payloads = {"subtensor.wasm": code, "upgrade-manifest.json": json.dumps(manifest).encode(),
                "subtensor-digest.json": json.dumps(release(code, commit)["digest"]).encode()}
    assets = [{"name": name, "id": i, "url": base + f"assets/{i}",
               "size": len(data), "state": "uploaded",
               "digest": "sha256:" + hashlib.sha256(data).hexdigest()}
              for i, (name, data) in enumerate(payloads.items(), 1)]
    metadata = {"id": 123, "tag_name": f"v{spec}", "target_commitish": commit,
                "draft": False, "prerelease": False, "assets": assets}
    responses = {a["url"]: payloads[a["name"]] for a in assets}
    responses[base + f"tags/v{spec}"] = json.dumps(metadata).encode()
    monkeypatch.setattr(module, "_download", lambda url, **kw: responses[url], raising=False)
    return metadata, responses


def test_official_downloader_produces_trusted_publisher_mapping(tmp_path, monkeypatch):
    module = evidence()
    repo, old, _ = repository(tmp_path)
    git(repo, "tag", "v467", old)
    official_download(monkeypatch, module, old)
    assert hasattr(module, "fetch_release"), "official release downloader missing"
    receipt = module.fetch_release(467, repo, tmp_path / "cache")
    assert isinstance(receipt, module.TrustedRelease)
    result = module.verify_release(pin(), receipt)
    assert result["status"] == "ready"
    assert result["source_verified"] is True
    assert result["source_provenance"] == "publisher-declared build source"
    assert result["independent_reproducible_build_attestation"] is False
    assert result["release_id"] == 123
    assert result["source_commit"] == old
    # Serialization does not confer trust on arbitrary caller dictionaries.
    assert module.verify_release(pin(), dict(receipt))["source_verified"] is False


def test_trusted_packet_is_ready_for_semantic_review(tmp_path, monkeypatch):
    module = evidence()
    repo, old, new = repository(tmp_path)
    receipts = []
    for spec, commit in ((467, old), (468, new)):
        git(repo, "tag", f"v{spec}", commit)
        official_download(monkeypatch, module, commit, spec)
        receipts.append(module.fetch_release(spec, repo, tmp_path / "cache"))
    packet = module.build_evidence(pin(), pin(spec=468), source_repo=repo, atlas_repo=repo,
                                   output_dir=tmp_path / "packet", releases=receipts, chunk_bytes=64)
    assert packet["status"] == "ready", packet["blocked_reasons"]
    assert packet["complete"] is True
    assert packet["semantic_review_status"] == "pending"
    assert packet["blocked_reasons"] == []
    assert packet["source_diff"]["provenance"] == "publisher-declared build source"
    assert packet["review_coverage"]["migrations"]["status"] == "pending"
    assert packet["metadata_comparison"]["status"] == "pending"
    assert set(packet["source_diff"]["changed_paths"]) == {"README.md", "odd\nname", "runtime/migrations.rs"}
    assert b"".join((tmp_path / "packet" / c["path"]).read_bytes()
                    for c in packet["source_diff"]["chunks"]) == (tmp_path / "packet/source.diff").read_bytes()
    for label, receipt in zip(("old", "new"), receipts):
        for name in ("subtensor-digest.json", "upgrade-manifest.json"):
            raw = (tmp_path / "packet" / f"{label}.assets" / name).read_bytes()
            assert "sha256:" + hashlib.sha256(raw).hexdigest() == receipt["assets"][name]["digest"]


@pytest.mark.parametrize("fault", ["target", "draft", "tag", "asset_id", "asset_url",
    "api_digest", "size", "duplicate", "missing", "asset_bytes", "source_commit", "wasm_digest"])
def test_downloader_rejects_untrusted_or_inconsistent_release(tmp_path, monkeypatch, fault):
    module = evidence()
    repo, old, _ = repository(tmp_path)
    git(repo, "tag", "v467", old)
    metadata, responses = official_download(monkeypatch, module, old)
    asset = metadata["assets"][0]
    if fault == "target": metadata["target_commitish"] = "main"
    if fault == "draft": metadata["draft"] = True
    if fault == "tag": metadata["tag_name"] = "v468"
    if fault == "asset_id": asset["id"] = 0
    if fault == "asset_url": asset["url"] = "https://evil.invalid/asset"
    if fault == "api_digest": asset["digest"] = None
    if fault == "size": asset["size"] = 128 * 1024 * 1024
    if fault == "duplicate": metadata["assets"].append(dict(asset))
    if fault == "missing": metadata["assets"].pop()
    if fault == "asset_bytes": responses[asset["url"]] += b"corrupted"
    if fault in ("source_commit", "wasm_digest"):
        declaration = metadata["assets"][1]
        data = json.loads(responses[declaration["url"]])
        data["commit" if fault == "source_commit" else "wasm_sha256"] = "0" * 40
        raw = json.dumps(data).encode()
        responses[declaration["url"]] = raw
        declaration.update(size=len(raw), digest="sha256:" + hashlib.sha256(raw).hexdigest())
    responses[module._RELEASE_API + "tags/v467"] = json.dumps(metadata).encode()
    with pytest.raises(module.EvidenceBlocked):
        module.fetch_release(467, repo, tmp_path / "cache")


def test_receipt_cannot_be_created_or_mutated_by_data(tmp_path, monkeypatch):
    module = evidence()
    with pytest.raises(module.EvidenceBlocked):
        module.TrustedRelease(release())
    repo, old, _ = repository(tmp_path)
    git(repo, "tag", "v467", old)
    official_download(monkeypatch, module, old)
    receipt = module.fetch_release(467, repo, tmp_path / "cache")
    receipt["manifest"]["commit"] = "b" * 40
    assert receipt["manifest"]["commit"] == old
    with pytest.raises(AttributeError):
        receipt._wasm = b"fake"


@pytest.mark.parametrize("url", ["http://release-assets.githubusercontent.com/x", "https://evil.invalid/x",
    "https://github.com.evil.invalid/x", "https://user@github.com/x", "https://github.com:444/x"])
def test_download_rejects_unapproved_hosts_before_network(url):
    module = evidence()
    with pytest.raises(module.EvidenceBlocked, match="host"):
        module._download(url, max_bytes=8)


def test_redirect_policy_checks_every_hop_and_download_bound(monkeypatch):
    import io
    import urllib.request
    module = evidence()
    assert hasattr(module, "_GithubRedirect"), "redirect host verification missing"
    handler = module._GithubRedirect()
    request = urllib.request.Request("https://api.github.com/repos/RaoFoundation/subtensor/releases/assets/1")
    for url in ("https://evil.invalid/x", "http://github.com/x"):
        with pytest.raises(module.EvidenceBlocked):
            handler.redirect_request(request, None, 302, "Found", {}, url)
    safe = "https://release-assets.githubusercontent.com/github-production-release-asset/x"
    assert handler.redirect_request(request, None, 302, "Found", {}, safe).full_url == safe
    class Opener:
        def open(self, request, timeout):
            return io.BytesIO(b"123456789")
    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *handlers: Opener())
    with pytest.raises(module.EvidenceBlocked, match="bound"):
        module._download(request.full_url, max_bytes=8)


def test_published_prerelease_is_valid_publisher_provenance(tmp_path, monkeypatch):
    module = evidence()
    repo, old, _ = repository(tmp_path)
    git(repo, "tag", "v467", old)
    metadata, responses = official_download(monkeypatch, module, old)
    metadata["prerelease"] = True  # Actual v467 is published as a prerelease.
    responses[module._RELEASE_API + "tags/v467"] = json.dumps(metadata).encode()
    receipt = module.fetch_release(467, repo, tmp_path / "cache")
    assert module.verify_release(pin(), receipt)["status"] == "ready"


def test_match_is_artifact_proof_not_source_attestation():
    module = evidence()
    assert hasattr(module, "verify_release"), "release verification missing"
    result = module.verify_release(pin(), release())
    assert result["artifact_match"] == "exact"
    assert result["source_commit"] == "a" * 40
    assert result["source_verified"] is False
    assert "unsigned" in result["blocked_reason"]


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "runtime").mkdir()
    (repo / "runtime/migrations.rs").write_text("old migration\n")
    (repo / "odd\nname").write_bytes(bytes(range(256)))
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "old")
    old = git(repo, "rev-parse", "HEAD").decode().strip()
    (repo / "runtime/migrations.rs").write_text("new migration\n" * 400)
    (repo / "odd\nname").write_bytes(bytes(reversed(range(256))))
    (repo / "README.md").write_text("docs")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "new")
    return repo, old, git(repo, "rev-parse", "HEAD").decode().strip()


def test_complete_candidate_packet_is_saved_but_provenance_blocks(tmp_path):
    repo, old, new = repository(tmp_path)
    output = tmp_path / "packet"
    result = evidence().build_evidence(pin(), pin(), source_repo=repo, atlas_repo=repo,
                                      output_dir=output,
                                      releases=(release(commit=old), release(commit=new)),
                                      chunk_bytes=64)
    assert result["status"] == "blocked"
    assert any("unsigned" in r for r in result["blocked_reasons"])
    assert result["source_diff"]["provenance"] == "candidate-only"
    assert set(result["source_diff"]["changed_paths"]) == {"README.md", "odd\nname", "runtime/migrations.rs"}
    chunks = result["source_diff"]["chunks"]
    assert len(chunks) > 2
    full = (output / "source.diff").read_bytes()
    assert b"GIT binary patch" in full
    assert b"".join((output / c["path"]).read_bytes() for c in chunks) == full
    assert chunks[-1]["end"] == len(full)
    assert result["source_diff"]["truncated"] is False
    assert len(result["atlas_inventory"]["files"]) == 3
    assert "runtime" in result["atlas_inventory"]["subsystems"]
    assert result["review_coverage"]["migrations"]["status"] == "pending"
    assert result["metadata_comparison"]["status"] == "pending"
    assert (output / "old.metadata.scale").read_bytes() == bytes.fromhex(pin()["metadata"][2:])
    stored = json.loads((output / "packet.json").read_text())
    for item in stored["file_manifest"]:
        data = (output / item["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == item["sha256"]


def compressed_wasm(raw):
    import ctypes
    import ctypes.util
    lib = ctypes.CDLL(ctypes.util.find_library("zstd"))
    lib.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
    lib.ZSTD_compressBound.restype = ctypes.c_size_t
    lib.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.c_int]
    lib.ZSTD_compress.restype = ctypes.c_size_t
    capacity = lib.ZSTD_compressBound(len(raw))
    dst = ctypes.create_string_buffer(capacity)
    size = lib.ZSTD_compress(dst, capacity, raw, len(raw), 1)
    return bytes.fromhex("52bc537646db8e05") + dst.raw[:size]


def test_compressed_wasm_matches_only_after_bounded_normalization():
    module = evidence()
    raw = b"\x00asm\x01\x00\x00\x00" + b"x" * 100
    packed = compressed_wasm(raw)
    result = module.verify_release(pin(raw), release(packed))
    assert result["artifact_match"] == "decompressed-equivalent"
    assert result["source_verified"] is False
    assert module.normalize_wasm(packed, max_bytes=200) == raw
    with pytest.raises(module.EvidenceBlocked, match="bound"):
        module.normalize_wasm(packed, max_bytes=32)
    with pytest.raises(module.EvidenceBlocked):
        module.normalize_wasm(packed[:-1])
    with pytest.raises(module.EvidenceBlocked):
        module.normalize_wasm(packed + b"trailing")
    with pytest.raises(module.EvidenceBlocked):
        module.normalize_wasm(b"not wasm")


@pytest.mark.parametrize("field,value", [("block_hash", "latest"), ("genesis_hash", "0x11"),
                                         ("code", "zz0061736d01000000"),
                                         ("metadata", "0x"), ("block_number", -1)])
def test_bad_pinned_input_is_blocked(tmp_path, field, value):
    p = pin()
    p[field] = value
    result = evidence().build_evidence(p, p, source_repo=tmp_path, atlas_repo=tmp_path,
                                      output_dir=tmp_path / "packet")
    assert any("invalid pinned runtime" in r for r in result["blocked_reasons"])


def test_partial_history_blocks_even_when_endpoint_trees_exist(tmp_path):
    repo, old, new = repository(tmp_path)
    # A shallow boundary is insufficient for full intervening-source history.
    (repo / ".git/shallow").write_text(old + "\n")
    result = evidence().build_evidence(pin(), pin(), source_repo=repo, atlas_repo=repo,
                                      output_dir=tmp_path / "packet",
                                      releases=(release(commit=old), release(commit=new)))
    assert any("partial source history" in r for r in result["blocked_reasons"])


def test_null_storage_is_not_a_deletion():
    module = evidence()
    assert hasattr(module, "storage_semantics"), "storage semantics missing"
    entry = {"modifier": "Default", "default": "0x01000000"}
    assert module.storage_semantics(entry, None)["state"] == "unset_uses_default"
    assert module.storage_semantics(entry, None)["default"] == "0x01000000"
    assert module.storage_semantics(None, None)["state"] == "unknown"
    assert module.storage_semantics(None, None, metadata_complete=True)["state"] == "absent_from_metadata"
    assert module.storage_semantics({"modifier": "Optional"}, None)["state"] == "unset_optional"
    assert module.storage_semantics(entry, "0x00")["state"] == "stored"


@pytest.mark.parametrize("fault,reason", [
    ("ambiguous", "ambiguous"), ("mismatch", "artifact mismatch"),
    ("code_hash", "code hash mismatch"), ("digest", "digest mismatch"),
    ("version", "runtime version mismatch"), ("commit", "invalid source commit")])
def test_artifact_failure_modes(fault, reason):
    module = evidence()
    p, r = pin(), release()
    if fault == "ambiguous": r["tag_commit"] = "b" * 40
    if fault == "mismatch": r["wasm"] += b"different"
    if fault == "code_hash": p["code_hash"] = "0x" + "00" * 32
    if fault == "digest": r["digest"]["sha256"] = "0x" + "00" * 32
    if fault == "version": r["manifest"]["spec_version"] = 468
    if fault == "commit": r["manifest"]["commit"] = "v467"
    with pytest.raises(module.EvidenceBlocked, match=reason):
        module.verify_release(p, r)


def test_existing_packet_is_not_overwritten(tmp_path):
    (tmp_path / "packet.json").write_text("user data")
    result = evidence().build_evidence(pin(), pin(), source_repo=tmp_path,
                                      atlas_repo=tmp_path, output_dir=tmp_path)
    assert result["status"] == "blocked"
    assert "output directory" in result["blocked_reasons"][0]
    assert (tmp_path / "packet.json").read_text() == "user data"


def test_tag_alone_is_blocked(tmp_path):
    path = Path(__file__).parents[1] / "evidence.py"
    assert path.exists(), "evidence module is not implemented"
    spec = importlib.util.spec_from_file_location("evidence", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.build_evidence({"tag": "v467"}, {"tag": "v468"},
                                   source_repo=tmp_path, atlas_repo=tmp_path,
                                   output_dir=tmp_path / "packet")
    assert result["status"] == "blocked"
    assert "pinned runtime" in result["blocked_reasons"][0]
