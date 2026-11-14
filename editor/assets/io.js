// Where the files come from and where a commit goes:
//   GitHub   read (no token needed: the repository is public), commit with a token
//   local    `guaminsects edit` in a clone: read the working tree, commit + push with git
//   folder   a clone opened in Chrome/Edge (File System Access): read, save the files back
//   files    any browser: pick the CSV files; save = download the changed ones
(function () {
  "use strict";
  const S = window.IOG_SPEC;
  const API = "https://api.github.com";
  // Keep a byte-order mark (taxonomy.csv has one): Response.text() and File.text() drop it,
  // and then every file would look changed.
  const decode = buf => new TextDecoder("utf-8", { ignoreBOM: true }).decode(buf);

  function headers(token, accept) {
    const h = { Accept: accept || "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" };
    if (token) h.Authorization = "Bearer " + token;
    return h;
  }
  async function gh(path, opts) {
    opts = opts || {};
    const res = await fetch(API + path, {
      method: opts.method || "GET", headers: Object.assign(headers(opts.token, opts.accept),
        opts.body ? { "Content-Type": "application/json" } : {}),
      body: opts.body ? JSON.stringify(opts.body) : undefined, cache: "no-store" });
    if (opts.allow404 && res.status === 404) return null;
    if (!res.ok) {
      let msg = res.status + " " + res.statusText;
      try { const j = await res.json(); if (j.message) msg = j.message + " (" + res.status + ")"; } catch (e) { /* not JSON */ }
      const err = new Error("GitHub: " + msg);
      err.status = res.status;
      throw err;
    }
    return opts.raw ? decode(await res.arrayBuffer()) : res.json();
  }

  async function loadGitHub(o) {
    const repo = o.repo || S.repo, branch = o.branch || S.branch;
    const commit = await gh(`/repos/${repo}/commits/${encodeURIComponent(branch)}`, { token: o.token });
    const sha = commit.sha, texts = {};
    await Promise.all(S.files.map(async path => {
      if (o.token) {
        texts[path] = await gh(`/repos/${repo}/contents/${path}?ref=${sha}`,
          { token: o.token, accept: "application/vnd.github.raw+json", raw: true, allow404: true });
      } else {              // raw.githubusercontent.com: no rate limit, CORS open
        const res = await fetch(`https://raw.githubusercontent.com/${repo}/${sha}/${path}`, { cache: "no-store" });
        if (res.status === 404) texts[path] = null;
        else if (!res.ok) throw new Error(`GitHub: ${path}: ${res.status}`);
        else texts[path] = decode(await res.arrayBuffer());
      }
    }));
    return { texts, source: { kind: "github", repo, branch, sha,
      label: `${repo}@${branch} ${sha.slice(0, 7)}`, date: commit.commit && commit.commit.committer.date } };
  }

  // One commit with every changed file, straight onto the branch. Throws err.moved (with
  // err.head) when the branch moved since `baseSha`: reload, replay, try again.
  async function commitGitHub(o) {
    const repo = o.repo || S.repo, branch = o.branch || S.branch, token = o.token;
    const ref = await gh(`/repos/${repo}/git/ref/heads/${encodeURIComponent(branch)}`, { token });
    const head = ref.object.sha;
    if (head !== o.baseSha) { const e = new Error("the branch moved on"); e.moved = true; e.head = head; throw e; }
    const tree = [];
    for (const [path, content] of Object.entries(o.files)) {
      const blob = await gh(`/repos/${repo}/git/blobs`, { token, method: "POST", body: { content, encoding: "utf-8" } });
      tree.push({ path, mode: "100644", type: "blob", sha: blob.sha });
    }
    const parent = await gh(`/repos/${repo}/git/commits/${head}`, { token });
    const t = await gh(`/repos/${repo}/git/trees`, { token, method: "POST", body: { base_tree: parent.tree.sha, tree } });
    const c = await gh(`/repos/${repo}/git/commits`, { token, method: "POST", body: { message: o.message, tree: t.sha, parents: [head] } });
    try {
      await gh(`/repos/${repo}/git/refs/heads/${encodeURIComponent(branch)}`, { token, method: "PATCH", body: { sha: c.sha, force: false } });
    } catch (e) {
      if (e.status === 422) { const m = new Error("the branch moved on"); m.moved = true; throw m; }
      throw e;
    }
    return { sha: c.sha, url: `https://github.com/${repo}/commit/${c.sha}` };
  }

  async function tokenUser(token) {
    const u = await gh("/user", { token });
    return u.login;
  }

  // The rebuild started by a commit (the workflow run for it), or null while none shows yet.
  async function rebuildStatus(o) {
    const repo = o.repo || S.repo;
    let j;
    try { j = await gh(`/repos/${repo}/actions/runs?head_sha=${o.sha}&per_page=5`, { token: o.token }); }
    catch (e) { j = await gh(`/repos/${repo}/actions/runs?head_sha=${o.sha}&per_page=5`); }
    const run = (j.workflow_runs || [])[0];
    return run ? { status: run.status, conclusion: run.conclusion, url: run.html_url, name: run.name } : null;
  }

  // ---------------------------------------------------------------- `guaminsects edit`
  async function localInfo() {
    if (!/^https?:$/.test(location.protocol)) return null;
    try {
      const res = await fetch("/api/editor/info", { cache: "no-store" });
      return res.ok ? res.json() : null;
    } catch (e) { return null; }
  }
  async function loadLocal() {
    const info = await localInfo();
    if (!info) throw new Error("no local editor server (run `uv run guaminsects edit` in the clone)");
    const texts = {};
    await Promise.all(S.files.map(async path => {
      const res = await fetch("/" + path, { cache: "no-store" });
      texts[path] = res.ok ? decode(await res.arrayBuffer()) : null;
    }));
    return { texts, info, source: { kind: "local", sha: info.head, branch: info.branch,
      label: `this clone (${info.branch} ${info.head.slice(0, 7)})` } };
  }
  async function commitLocal(o) {
    const res = await fetch("/api/editor/commit", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ files: o.files, message: o.message, author: o.author, base: o.baseSha }) });
    const j = await res.json();
    if (res.status === 409 && j.head) { const e = new Error(j.errors.join("; ")); e.moved = true; e.head = j.head; throw e; }
    if (!res.ok || !j.ok) throw new Error((j.errors || [j.error || res.statusText]).join("\n"));
    return j;
  }

  // ---------------------------------------------------------------- folder (Chrome, Edge)
  const canFolder = () => typeof window.showDirectoryPicker === "function";
  async function fileIn(dir, path, create) {
    const parts = path.split("/");
    let d = dir;
    for (const p of parts.slice(0, -1)) d = await d.getDirectoryHandle(p, { create: !!create });
    return d.getFileHandle(parts[parts.length - 1], { create: !!create });
  }
  async function pickFolder() {
    const dir = await window.showDirectoryPicker({ id: "guam-insects", mode: "readwrite" });
    return loadFolder(dir);
  }
  async function loadFolder(dir) {
    const texts = {};
    for (const path of S.files) {
      try { texts[path] = decode(await (await (await fileIn(dir, path)).getFile()).arrayBuffer()); }
      catch (e) { texts[path] = null; }
    }
    if (texts["taxonomy.csv"] == null) throw new Error(`no taxonomy.csv in the folder "${dir.name}": pick the top of the clone`);
    return { texts, dir, source: { kind: "folder", label: `folder ${dir.name}`, sha: "folder:" + dir.name } };
  }
  async function saveFolder(dir, files) {
    for (const [path, text] of Object.entries(files)) {
      const w = await (await fileIn(dir, path, true)).createWritable();
      await w.write(new Blob([text], { type: "text/csv" }));
      await w.close();
    }
  }

  // ---------------------------------------------------------------- plain files
  async function loadFiles(fileList) {
    const byName = {};
    for (const f of fileList) byName[f.name] = f;
    const texts = {};
    for (const path of S.files) {
      const f = byName[path.split("/").pop()];
      texts[path] = f ? decode(await f.arrayBuffer()) : null;
    }
    if (texts["taxonomy.csv"] == null) throw new Error("taxonomy.csv was not among the files");
    return { texts, source: { kind: "files", label: Object.keys(byName).join(", "), sha: "files" } };
  }
  function download(files) {
    for (const [path, text] of Object.entries(files)) {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
      a.download = path.replace("/", "_");
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    }
  }

  window.IOGIO = { loadGitHub, commitGitHub, tokenUser, rebuildStatus, localInfo, loadLocal,
                   commitLocal, canFolder, pickFolder, loadFolder, saveFolder, loadFiles, download };
})();
