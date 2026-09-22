"""Read-only, store-independent runtime evidence collection."""

import ctypes
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from collections.abc import Mapping
from urllib.parse import urlsplit
import urllib.request


_RELEASE_API = "https://api.github.com/repos/RaoFoundation/subtensor/releases/"
_RECEIPT_TOKEN = object()


class TrustedRelease(Mapping):
    """In-process downloader receipt, not a portable attestation.

    Only fetch_release creates these. JSON copies deliberately lose trust.
    Callers are trusted Python harness code, not adversarial Python execution.
    Values are copied on access to prevent mutation of verified declarations.
    """
    __slots__ = ("_wasm", "_json")

    def __init__(self, values, *, _token=None):
        if _token is not _RECEIPT_TOKEN:
            raise EvidenceBlocked("trusted receipt must originate from fetch_release")
        object.__setattr__(self, "_wasm", values["wasm"])
        object.__setattr__(self, "_json", json.dumps({k: v for k, v in values.items() if k != "wasm"}))

    def __setattr__(self, name, value):
        raise AttributeError("immutable release receipt")

    def __getitem__(self, key):
        return self._wasm if key == "wasm" else json.loads(self._json)[key]

    def __iter__(self):
        return iter(["wasm", *json.loads(self._json)])

    def __len__(self):
        return 1 + len(json.loads(self._json))


def _github_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in {
            "api.github.com", "github.com", "release-assets.githubusercontent.com",
            "objects.githubusercontent.com"}
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443)):
        raise EvidenceBlocked("unapproved release download host")


class _GithubRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _github_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(url, *, max_bytes, accept="application/vnd.github+json"):
    _github_url(url)
    request = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "atlas-maintenance"})
    with urllib.request.build_opener(_GithubRedirect()).open(request, timeout=60) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise EvidenceBlocked("release download exceeds bound")
    return data


def fetch_release(spec, source_repo, cache_dir):
    """Fetch official publisher provenance; never trust cache files as receipts.

    Returns TrustedRelease; raises EvidenceBlocked on missing/mismatched data.
    source_repo is read-only and must contain refs/tags/v{spec}. Cache retains
    exact API/asset bytes by release/asset ID for later review, not reuse.
    """
    try:
        if type(spec) is not int or spec < 0:
            raise EvidenceBlocked("invalid release spec")
        tag = f"v{spec}"
        commit = _git(source_repo, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}").decode().strip()
        url = _RELEASE_API + "tags/" + tag
        raw = _download(url, max_bytes=2 * 1024 * 1024)
        metadata = json.loads(raw)
        if (not re.fullmatch(r"[0-9a-f]{40}", commit)
                or metadata["tag_name"] != tag or metadata["target_commitish"] != commit
                or metadata["draft"] is not False
                or type(metadata["id"]) is not int or metadata["id"] <= 0):
            raise EvidenceBlocked("official release tag/target commit mismatch")
        blobs, receipts = {}, {}
        for name in ("subtensor.wasm", "subtensor-digest.json", "upgrade-manifest.json"):
            candidates = [a for a in metadata["assets"] if a["name"] == name]
            if len(candidates) != 1:
                raise EvidenceBlocked("missing or duplicate release asset: " + name)
            asset = candidates[0]
            limit = 64 * 1024 * 1024 if name.endswith(".wasm") else 2 * 1024 * 1024
            if (type(asset["id"]) is not int or asset["id"] <= 0
                    or asset["url"] != _RELEASE_API + f'assets/{asset["id"]}'
                    or asset["state"] != "uploaded"
                    or type(asset["size"]) is not int or not 0 < asset["size"] <= limit
                    or not re.fullmatch(r"sha256:[0-9a-f]{64}", asset["digest"] or "")):
                raise EvidenceBlocked("invalid immutable asset identity/digest/bound")
            data = _download(asset["url"], max_bytes=limit, accept="application/octet-stream")
            if len(data) != asset["size"] or "sha256:" + hashlib.sha256(data).hexdigest() != asset["digest"]:
                raise EvidenceBlocked("API asset digest/size mismatch")
            blobs[name] = data
            receipts[name] = {k: asset[k] for k in ("id", "url", "size", "digest")}
        manifest = json.loads(blobs["upgrade-manifest.json"])
        digest = json.loads(blobs["subtensor-digest.json"])
        sha = "0x" + hashlib.sha256(blobs["subtensor.wasm"]).hexdigest()
        if (manifest["commit"] != commit or digest["commit"] != commit
                or manifest["spec_version"] != spec or manifest["tag"] != tag
                or manifest["repo"] != "RaoFoundation/subtensor" or manifest["network"] != "finney"
                or manifest["wasm_sha256"] != sha or digest["sha256"] != sha):
            raise EvidenceBlocked("publisher source/manifest/digest mismatch")
        normalize_wasm(blobs["subtensor.wasm"])
        values = {"wasm": blobs["subtensor.wasm"], "manifest": manifest, "digest": digest,
                  "tag_commit": commit, "url": url, "release_id": metadata["id"],
                  "assets": receipts, "release_metadata": metadata,
                  "raw_asset_hex": {name: data.hex() for name, data in blobs.items()
                                    if name != "subtensor.wasm"},
                  "raw_release_api_hex": raw.hex()}
        cache = Path(cache_dir) / f'{tag}-{metadata["id"]}'
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "release-api.json").write_bytes(raw)
        for name, data in blobs.items():
            (cache / f'{receipts[name]["id"]}-{name}').write_bytes(data)
        return TrustedRelease(values, _token=_RECEIPT_TOKEN)
    except EvidenceBlocked:
        raise
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        raise EvidenceBlocked("official release fetch failed: " + str(exc)) from exc


class EvidenceBlocked(ValueError):
    """Evidence is absent, inconsistent, or beyond a configured bound."""


def normalize_wasm(data, *, max_bytes=64 * 1024 * 1024):
    """Decode Substrate's zstd wrapper with a hard output allocation bound.

    Hash original :code separately. Compression equivalence does not mean the
    original storage hashes match. Reject multiple frames and trailing bytes.
    Uses system libzstd; absence is an explicit blocker, never a Rust rebuild.
    """
    if not isinstance(data, bytes) or len(data) > max_bytes or max_bytes <= 0:
        raise EvidenceBlocked("wasm input exceeds bound")
    if data.startswith(bytes.fromhex("52bc537646db8e05")):
        library = ctypes.util.find_library("zstd")
        if not library:
            raise EvidenceBlocked("libzstd unavailable")
        lib = ctypes.CDLL(library)
        src = data[8:]
        lib.ZSTD_findFrameCompressedSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        lib.ZSTD_findFrameCompressedSize.restype = ctypes.c_size_t
        lib.ZSTD_getFrameContentSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        lib.ZSTD_getFrameContentSize.restype = ctypes.c_ulonglong
        lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
        lib.ZSTD_isError.restype = ctypes.c_uint
        lib.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                       ctypes.c_void_p, ctypes.c_size_t]
        lib.ZSTD_decompress.restype = ctypes.c_size_t
        frame_size = lib.ZSTD_findFrameCompressedSize(src, len(src))
        if lib.ZSTD_isError(frame_size) or frame_size != len(src):
            raise EvidenceBlocked("invalid or trailing compressed wasm frame")
        size = lib.ZSTD_getFrameContentSize(src, len(src))
        unknown, invalid = (1 << 64) - 1, (1 << 64) - 2
        if size == invalid:
            raise EvidenceBlocked("invalid compressed wasm")
        if size != unknown and size > max_bytes:
            raise EvidenceBlocked("decompressed wasm exceeds bound")
        capacity = max_bytes if size == unknown else size
        dst = ctypes.create_string_buffer(capacity)
        actual = lib.ZSTD_decompress(dst, capacity, src, len(src))
        if lib.ZSTD_isError(actual) or actual > max_bytes:
            raise EvidenceBlocked("invalid compressed wasm or output exceeds bound")
        data = dst.raw[:actual]
    if not data.startswith(b"\x00asm\x01\x00\x00\x00"):
        raise EvidenceBlocked("invalid wasm header")
    return data


def _validate_pin(pinned):
    required = {"genesis_hash", "block_hash", "block_number", "runtime_version",
                "code", "code_hash", "metadata"}
    if not isinstance(pinned, dict) or not required.issubset(pinned):
        raise EvidenceBlocked("missing pinned runtime evidence")
    for key in ("genesis_hash", "block_hash", "code_hash"):
        if not isinstance(pinned[key], str) or not re.fullmatch(r"0x[0-9a-f]{64}", pinned[key]):
            raise EvidenceBlocked("invalid pinned runtime " + key)
    if type(pinned["block_number"]) is not int or pinned["block_number"] < 0:
        raise EvidenceBlocked("invalid pinned runtime block_number")
    version = pinned["runtime_version"]
    if not isinstance(version, dict) or type(version.get("specVersion")) is not int or version["specVersion"] < 0:
        raise EvidenceBlocked("invalid pinned runtime version")
    for key in ("code", "metadata"):
        value = pinned[key]
        if (not isinstance(value, str) or len(value) > 128 * 1024 * 1024 + 2
                or len(value) % 2 or not re.fullmatch(r"0x[0-9a-fA-F]+", value)):
            raise EvidenceBlocked("invalid pinned runtime " + key)
    if not bytes.fromhex(pinned["metadata"][2:]).startswith(b"meta"):
        raise EvidenceBlocked("invalid pinned runtime metadata magic")
    code = bytes.fromhex(pinned["code"][2:])
    if pinned["code_hash"] != "0x" + hashlib.blake2b(code, digest_size=32).hexdigest():
        raise EvidenceBlocked("pinned runtime code hash mismatch")


def verify_release(pinned, release):
    """Match chain bytes and approved publisher provenance, not rebuild proof."""
    _validate_pin(pinned)
    code = bytes.fromhex(pinned["code"][2:])
    wasm = release["wasm"]
    if pinned["code_hash"] != "0x" + hashlib.blake2b(code, digest_size=32).hexdigest():
        raise EvidenceBlocked("pinned runtime code hash mismatch")
    if normalize_wasm(code) != normalize_wasm(wasm):
        raise EvidenceBlocked("runtime artifact mismatch")
    sha = "0x" + hashlib.sha256(wasm).hexdigest()
    manifest, digest = release["manifest"], release["digest"]
    commit = manifest["commit"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise EvidenceBlocked("invalid source commit")
    if digest["commit"] != commit or release["tag_commit"] != commit:
        raise EvidenceBlocked("ambiguous source commit")
    if manifest["wasm_sha256"] != sha or digest["sha256"] != sha:
        raise EvidenceBlocked("release digest mismatch")
    if manifest["spec_version"] != pinned["runtime_version"]["specVersion"]:
        raise EvidenceBlocked("release runtime version mismatch")
    if isinstance(release, TrustedRelease):
        return {"status": "ready", "artifact_match": "exact" if code == wasm else "decompressed-equivalent",
                "source_commit": commit, "artifact_sha256": sha, "chain_code_hash": pinned["code_hash"],
                "source_verified": True, "source_provenance": "publisher-declared build source",
                "independent_reproducible_build_attestation": False,
                "release_id": release["release_id"], "assets": release["assets"]}
    return {"artifact_match": "exact" if code == wasm else "decompressed-equivalent", "source_commit": commit,
            "artifact_sha256": sha, "chain_code_hash": pinned["code_hash"],
            "source_verified": False,
            "blocked_reason": "unsigned release manifests do not attest artifact-to-source build provenance"}


def storage_semantics(metadata_entry, raw_value, *, metadata_complete=False):
    """Classify a pinned query without confusing unset with removed storage.

    Caller must supply the decoded metadata entry from the SAME block. An
    absent entry is meaningful only if decoding/lookup coverage is complete.
    This says nothing about whether a governance-controlled feature is active.
    """
    if metadata_entry is None:
        return {"state": "absent_from_metadata" if metadata_complete else "unknown"}
    if raw_value is not None:
        return {"state": "stored", "raw": raw_value}
    if metadata_entry.get("modifier") == "Default" and "default" in metadata_entry:
        return {"state": "unset_uses_default", "default": metadata_entry["default"]}
    if metadata_entry.get("modifier") == "Optional":
        return {"state": "unset_optional"}
    return {"state": "unknown"}


def _git(repo, *args):
    return subprocess.check_output(
        ["git", "--no-replace-objects", "-C", str(repo), *args],
        stderr=subprocess.PIPE, timeout=120,
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_OPTIONAL_LOCKS": "0"})


def _tree(repo, commit):
    files = []
    for record in _git(repo, "ls-tree", "-rz", "--full-tree", commit).split(b"\0"):
        if record:
            attributes, path = record.split(b"\t", 1)
            mode, kind, oid = attributes.decode().split()
            files.append({"path": path.decode("utf-8", "surrogateescape"),
                          "mode": mode, "kind": kind, "oid": oid})
    return files


def build_evidence(old, new, *, source_repo, atlas_repo, output_dir,
                   releases=None, chunk_bytes=1024 * 1024):
    """Build a complete review packet, not a completed semantic audit.

    Pinned dicts require genesis_hash, block_hash, block_number, runtime_version,
    code (0x storage bytes), code_hash (Blake2-256), and metadata (0x SCALE).
    ``releases`` is a pair of TrustedRelease receipts from fetch_release.
    Raw dictionaries remain blocked candidates. Approved publisher provenance
    makes evidence ready for review, not independently reproducible-build
    attested, semantically reviewed, or authorized for downstream mutation.
    Output must be a new directory. Input repos are read-only; no hooks run.
    """
    packet = {"schema_version": 1, "status": "blocked", "complete": False,
              "semantic_review_status": "pending", "blocked_reasons": [],
              "file_manifest": [], "deployments": {}, "review_coverage": {}}
    reasons = packet["blocked_reasons"]
    out = Path(output_dir)
    try:
        out.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        reasons.append("cannot create fresh output directory: " + str(exc))
        return packet

    def save(name, data):
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        item = {"path": name, "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest()}
        packet["file_manifest"].append(item)
        return item

    def save_json(name, obj):
        return save(name, (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode())

    try:
        if not isinstance(chunk_bytes, int) or chunk_bytes <= 0:
            raise EvidenceBlocked("chunk_bytes must be positive")
        for pinned in (old, new):
            _validate_pin(pinned)
        if old["genesis_hash"] != new["genesis_hash"]:
            raise EvidenceBlocked("pinned runtime genesis mismatch")
        for label, pinned in (("old", old), ("new", new)):
            save_json(label + ".pinned.json", pinned)
            save(label + ".metadata.scale", bytes.fromhex(pinned["metadata"][2:]))
            save(label + ".code.wasm", bytes.fromhex(pinned["code"][2:]))
            packet["deployments"][label] = {k: v for k, v in pinned.items()
                                               if k not in ("code", "metadata")}
        packet["metadata_comparison"] = {
            "old": "old.metadata.scale", "new": "new.metadata.scale", "status": "pending",
            "warning": "raw null storage does not establish removal; consult metadata, query semantics and defaults"}
        atlas_commit = _git(atlas_repo, "rev-parse", "HEAD").decode().strip()
        files = _tree(atlas_repo, atlas_commit)
        subsystems = {}
        for item in files:
            group = item["path"].split("/", 1)[0] if "/" in item["path"] else "root"
            subsystems.setdefault(group, {"paths": [], "disposition": "pending"})["paths"].append(item["path"])
        packet["atlas_inventory"] = {"commit": atlas_commit, "files": files, "subsystems": subsystems}
        save_json("atlas-inventory.json", packet["atlas_inventory"])
        if releases is None or len(releases) != 2:
            raise EvidenceBlocked("missing release artifact provenance")
        mappings = []
        for label, pinned, artifact in zip(("old", "new"), (old, new), releases):
            result = verify_release(pinned, artifact)
            mappings.append(result)
            packet["deployments"][label]["mapping"] = result
            if not result["source_verified"]:
                reasons.append(label + ": " + result["blocked_reason"])
            save(label + ".release.wasm", artifact["wasm"])
            save_json(label + ".release.json", {k: v for k, v in artifact.items() if k != "wasm"})
            if isinstance(artifact, TrustedRelease):
                for name, hex_data in artifact["raw_asset_hex"].items():
                    save(label + ".assets/" + name, bytes.fromhex(hex_data))
                save(label + ".release-api.json", bytes.fromhex(artifact["raw_release_api_hex"]))
        commits = [m["source_commit"] for m in mappings]
        if _git(source_repo, "rev-parse", "--is-shallow-repository").strip() != b"false":
            raise EvidenceBlocked("partial source history: shallow repository")
        for label, commit in zip(("old", "new"), commits):
            if _git(source_repo, "rev-parse", "--verify", commit + "^{commit}").decode().strip() != commit:
                raise EvidenceBlocked("source commit unavailable")
            save_json(label + ".source-tree.json", _tree(source_repo, commit))
        paths = [p.decode("utf-8", "surrogateescape") for p in
                 _git(source_repo, "diff", "--no-ext-diff", "--no-textconv", "--no-renames",
                      "--name-only", "-z", *commits, "--").split(b"\0") if p]
        diff = _git(source_repo, "diff", "--no-ext-diff", "--no-textconv", "--no-renames",
                    "--binary", "--full-index", "--no-color", *commits, "--")
        save("source.diff", diff)
        chunks = []
        for index, start in enumerate(range(0, len(diff), chunk_bytes)):
            item = save(f"chunks/{index:06d}.diff", diff[start:start + chunk_bytes])
            chunks.append({**item, "start": start, "end": start + item["size"]})
        packet["source_diff"] = {
            "provenance": "publisher-declared build source" if not reasons else "candidate-only",
            "independent_reproducible_build_attestation": False,
            "old_commit": commits[0], "new_commit": commits[1],
            "changed_paths": paths, "path_count": len(paths), "chunks": chunks,
            "byte_count": len(diff), "truncated": False,
            "path_reviews": [{"path": p, "disposition": "pending"} for p in paths]}
        topics = ("migrations", "calls", "storage", "defaults", "constants", "events",
                  "runtime_apis", "economics", "sdk_schema", "dependencies", "governance_activation")
        for topic in topics:
            packet["review_coverage"][topic] = {
                "status": "pending", "evidence": [],
                "required": "review full source diff, metadata and pinned chain reads; source presence does not prove activation"}
        save_json("coverage.json", {"source": packet["source_diff"],
                                   "topics": packet["review_coverage"]})
        if not reasons:
            packet.update(status="ready", complete=True)
    except (EvidenceBlocked, KeyError, TypeError, ValueError, OSError,
            subprocess.SubprocessError) as exc:
        reasons.append(str(exc))
    # Manifest intentionally excludes packet.json to avoid a recursive checksum.
    (out / "packet.json").write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n")
    return packet
